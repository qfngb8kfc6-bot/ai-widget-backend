from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from collections import defaultdict
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI(title="AI Widget Backend")

# --------------------------------------------------
# CORS (allow widget + GitHub Pages)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock later per domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING
# --------------------------------------------------
API_KEYS = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "usage": 0
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
        "usage": 0
    }
}

USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: str
    industry: str
    goal: str
    host_url: Optional[str] = None  # ✅ the page the widget is embedded on

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "").strip()

    for client, data in API_KEYS.items():
        if key == data["key"]:
            origin = request.headers.get("origin", "")  # e.g. https://xxx.github.io
            allowed_domains = data["domains"]

            if "*" not in allowed_domains:
                if origin:
                    if not any(domain in origin for domain in allowed_domains):
                        raise HTTPException(status_code=403, detail="Domain not allowed for this API key")
                # If no Origin header is present, we can’t enforce domain lock reliably.

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")


def normalize_site_root(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return None
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return None


def fetch_html(url: str, timeout: int = 8) -> str:
    # Basic safe fetch (no JS rendering)
    headers = {
        "User-Agent": "AIWidgetBot/1.0 (+https://example.com)"
    }
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text


def extract_service_phrases_from_html(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")

    # Remove junk
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    # Heuristic: look for common “service” keywords near nav/headings
    candidates = []

    # Grab headings + nav links (often contain service names)
    for tag in soup.find_all(["h1", "h2", "h3", "a", "li"]):
        t = (tag.get_text(" ", strip=True) or "").strip()
        if not t:
            continue
        if 3 <= len(t) <= 60:
            candidates.append(t)

    # Filter down to likely service phrases
    keywords = [
        "seo", "marketing", "design", "web", "website", "branding", "ads", "ppc",
        "social", "content", "copywriting", "development", "consulting",
        "automation", "email", "lead", "crm", "strategy"
    ]

    filtered = []
    seen = set()
    for c in candidates:
        c_low = c.lower()
        if any(k in c_low for k in keywords):
            # avoid duplicates
            norm = re.sub(r"[^a-z0-9]+", "-", c_low).strip("-")
            if norm and norm not in seen:
                seen.add(norm)
                filtered.append(c)

    # Keep it short
    return filtered[:12]


def recommend_services(industry: str, goal: str, host_services: List[str]) -> List[str]:
    recs = []

    if "marketing" in industry.lower():
        recs += ["Website copywriting", "Landing page creation", "SEO optimization"]

    if goal.lower() in ["lead generation", "leads", "more leads"]:
        recs += ["Lead funnel optimization", "Conversion rate optimization"]

    # If host site already mentions SEO/Ads/etc, suggest adjacent upgrades
    host_text = " ".join(host_services).lower()
    if "seo" in host_text:
        recs.append("Technical SEO audit")
    if "ads" in host_text or "ppc" in host_text:
        recs.append("Google Ads account optimization")
    if "web design" in host_text or "website" in host_text:
        recs.append("Website performance improvements")

    # Unique + stable
    out = []
    for r in recs:
        if r not in out:
            out.append(r)
    return out[:10]


# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/recommend")
def recommend(
    data: RequestData,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    client = verify_api_key(authorization, request)

    # Fetch host website (best effort)
    host_url = data.host_url or request.headers.get("referer") or ""
    host_root = normalize_site_root(host_url)

    host_services = []
    if host_root:
        try:
            html = fetch_html(host_root)
            host_services = extract_service_phrases_from_html(html)
        except:
            pass

    ranked = []

    def add(service, score, why):
        ranked.append({
            "service": service,
            "score": score,
            "why": why
        })

    # Core logic
    if "marketing" in data.industry.lower():
        add(
            "SEO optimization",
            88,
            "Your industry is marketing-focused and SEO improves inbound leads."
        )
        add(
            "Landing page optimization",
            82,
            "Landing pages convert traffic into leads more effectively."
        )

    if "lead" in data.goal.lower():
        add(
            "Lead funnel optimization",
            92,
            "Your goal is lead generation and funnel optimization maximizes conversions."
        )

    # Boost based on detected site services
    site_text = " ".join(host_services).lower()
    if "seo" in site_text:
        add(
            "Technical SEO audit",
            85,
            "Your site already mentions SEO — a technical audit can unlock more growth."
        )

    if not ranked:
        add(
            "Digital growth strategy",
            70,
            "A general strategy helps align your website with your business goals."
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return {
        "client": client,
        "ranked_services": ranked,
        "host_services_found": host_services
    }
