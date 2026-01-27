from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Dict, Any
from collections import defaultdict
from urllib.parse import urlparse
import os
import re
import time
import ipaddress
import socket

import requests
from bs4 import BeautifulSoup

# OpenAI (new SDK)
from openai import OpenAI

# -----------------------------
# App
# -----------------------------
app = FastAPI(title="AI Widget Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # domain-locking is enforced per API key below
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# OpenAI config
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")  # or another available model
client_ai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# -----------------------------
# API Keys + Domain Lock + Branding
# -----------------------------
API_KEYS: Dict[str, Dict[str, Any]] = {
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],  # allowed widget hosts
        "branding": {
            "name": "Demo",
            "primary": "#0B1020",
            "accent": "#2AAABE",
            "logo_url": ""
        }
    },
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "branding": {
            "name": "ACME",
            "primary": "#0B1020",
            "accent": "#3B82F6",
            "logo_url": "https://acme.com/logo.png"
        }
    }
}

# usage tracking (in-memory). For real SaaS, store in DB.
USAGE_COUNTER = defaultdict(int)
USAGE_LAST_SEEN = defaultdict(float)

# -----------------------------
# Request model (ONLY 3 fields)
# -----------------------------
class RecommendRequest(BaseModel):
    website_url: HttpUrl
    industry: str
    goal: str

# -----------------------------
# Helpers: safety + parsing
# -----------------------------
def get_origin_host(req: Request) -> str:
    origin = req.headers.get("origin") or ""
    if not origin:
        return ""
    try:
        return urlparse(origin).hostname or ""
    except Exception:
        return ""

def is_private_address(host: str) -> bool:
    # Blocks SSRF to private IP ranges even if user passes an IP
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
        for family, _, _, _, sockaddr in infos:
            if family in (socket.AF_INET, socket.AF_INET6):
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return True
    except Exception:
        # If DNS fails, treat as unsafe fetch
        return True

    return False

def validate_public_http_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="website_url must be http(s)")
    if not p.hostname:
        raise HTTPException(status_code=400, detail="Invalid website_url")
    if is_private_address(p.hostname):
        raise HTTPException(status_code=400, detail="website_url host not allowed")

def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format. Use Bearer <key>")

    key = authorization.replace("Bearer ", "").strip()
    origin_host = get_origin_host(request)

    for client_name, data in API_KEYS.items():
        if key == data["key"]:
            allowed = data.get("domains", [])
            # If origin is missing, we allow for server-to-server calls but you can tighten this.
            if origin_host:
                if "*" not in allowed and not any(
                    origin_host == d or origin_host.endswith("." + d) for d in allowed
                ):
                    raise HTTPException(status_code=403, detail="Domain not allowed for this API key")

            USAGE_COUNTER[client_name] += 1
            USAGE_LAST_SEEN[client_name] = time.time()
            return client_name

    raise HTTPException(status_code=403, detail="Invalid API key")

# -----------------------------
# Helpers: fetch + extract text
# -----------------------------
UA = "AIWidgetBot/1.0 (+https://example.com)"

def fetch_visible_text(url: str, max_chars: int = 9000) -> str:
    validate_public_http_url(url)

    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": UA})
        r.raise_for_status()
    except Exception:
        return ""

    html = r.text or ""
    soup = BeautifulSoup(html, "html.parser")

    # remove junk
    for tag in soup(["script", "style", "noscript", "svg", "img", "header", "footer", "nav"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    # keep only first chunk
    return text[:max_chars]

def safe_origin_homepage(origin_host: str) -> str:
    # If widget runs on https://site.com, we try https://site.com/
    if not origin_host:
        return ""
    # avoid private targets
    if is_private_address(origin_host):
        return ""
    return f"https://{origin_host}/"

# -----------------------------
# LLM: rank services with reasons + percents
# -----------------------------
def llm_rank_services(*, website_url: str, industry: str, goal: str,
                      website_text: str, host_site_url: str, host_site_text: str) -> Dict[str, Any]:
    if not client_ai:
        # fallback deterministic behavior if OPENAI_API_KEY missing
        base = []
        if "marketing" in industry.lower():
            base += ["SEO optimization", "Landing page creation", "Website copywriting"]
        if "lead" in goal.lower():
            base += ["Lead funnel optimization"]
        # simple scoring
        ranked = []
        seen = set()
        score = 90
        for s in base:
            if s in seen:
                continue
            seen.add(s)
            ranked.append({"service": s, "score": score, "why": "Matched your stated industry/goal."})
            score = max(55, score - 10)
        return {"ranked_services": ranked[:5]}

    system = (
        "You are an expert growth consultant. "
        "Given a company's website content + the host site where the widget is installed, "
        "recommend the best services to offer them. "
        "Return STRICT JSON only."
    )

    user = {
        "input": {
            "website_url": website_url,
            "industry": industry,
            "goal": goal,
            "website_text_snippet": website_text[:9000],
            "host_site_url": host_site_url,
            "host_site_text_snippet": host_site_text[:9000],
        },
        "instructions": {
            "output_rules": [
                "Return JSON with key ranked_services (array).",
                "Each item: service (string), score (integer 0-100), why (string).",
                "Scores should sum to roughly 250-350 across 4-6 items (not required, but avoid all 100s).",
                "Use the snippets to infer what the company likely does and what they already offer.",
                "Avoid recommending services they clearly already provide unless it is an upsell."
            ],
            "service_style": "plain business services list"
        }
    }

    # Responses API call (keep server-side). Keys must not be exposed client-side. :contentReference[oaicite:2]{index=2}
    resp = client_ai.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(user)},
        ],
    )

    # The SDK can return text; we parse JSON from it.
    text = resp.output_text.strip()
    # attempt to locate JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise HTTPException(status_code=502, detail="Model did not return JSON")
    import json
    data = json.loads(m.group(0))

    ranked = data.get("ranked_services", [])
    if not isinstance(ranked, list):
        raise HTTPException(status_code=502, detail="Bad model JSON format")

    # sanitize
    cleaned = []
    for item in ranked:
        if not isinstance(item, dict):
            continue
        service = str(item.get("service", "")).strip()
        why = str(item.get("why", "")).strip()
        try:
            score = int(item.get("score", 0))
        except Exception:
            score = 0
        score = max(0, min(100, score))
        if service:
            cleaned.append({"service": service, "score": score, "why": why})

    if not cleaned:
        cleaned = [{"service": "Consultation", "score": 70, "why": "Insufficient site data; start with discovery."}]

    return {"ranked_services": cleaned[:6]}

# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/recommend")
def recommend(
    data: RecommendRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    client_name = verify_api_key(authorization, request)

    website_url = str(data.website_url)
    origin_host = get_origin_host(request)
    host_site_url = safe_origin_homepage(origin_host)

    website_text = fetch_visible_text(website_url)
    host_site_text = fetch_visible_text(host_site_url) if host_site_url else ""

    result = llm_rank_services(
        website_url=website_url,
        industry=data.industry,
        goal=data.goal,
        website_text=website_text,
        host_site_url=host_site_url,
        host_site_text=host_site_text,
    )

    branding = API_KEYS.get(client_name, {}).get("branding", {})

    return {
        "client": client_name,
        "branding": branding,
        "ranked_services": result["ranked_services"],
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    # Return usage ONLY if the caller is a valid key.
    _ = verify_api_key(authorization, request)
    return {
        "usage": dict(USAGE_COUNTER),
        "last_seen_epoch": dict(USAGE_LAST_SEEN),
    }
