from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from collections import defaultdict
from urllib.parse import urlparse
import re
import socket
import ipaddress
import httpx

app = FastAPI(title="AI Widget Backend", version="2.0")

# --------------------------------------------------
# CORS (you can lock this down later)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ok for now. You already enforce domain via API key below.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING + BRANDING
# --------------------------------------------------
API_KEYS: Dict[str, Dict[str, Any]] = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "branding": {
            "name": "Acme AI",
            "logo_url": "",  # optional
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
        "branding": {
            "name": "AI Widget",
            "logo_url": "",
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
}

# Usage tracking (in-memory)
USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL (matches widget fields)
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: str = Field(..., description="Customer website to analyze")
    industry: str = Field(..., description="Industry provided by user")
    goal: str = Field(..., description="Goal provided by user")


# --------------------------------------------------
# SECURITY HELPERS (basic SSRF protection)
# --------------------------------------------------
def _is_private_ip(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
        return (
            obj.is_private
            or obj.is_loopback
            or obj.is_link_local
            or obj.is_reserved
            or obj.is_multicast
        )
    except Exception:
        return True


def _safe_http_url(url: str) -> str:
    """
    Validate URL: must be http(s), must have hostname, block private IPs/localhost.
    Returns normalized url.
    """
    if not url:
        raise ValueError("Empty URL")

    url = url.strip()

    # Add scheme if user typed "example.com"
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")
    if not p.hostname:
        raise ValueError("URL must include a hostname")

    host = p.hostname.lower()

    # Block obvious local names
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        raise ValueError("Localhost URLs are not allowed")

    # Resolve DNS -> IP, block private IPs
    try:
        ip = socket.gethostbyname(host)
        if _is_private_ip(ip):
            raise ValueError("Private/internal IPs are not allowed")
    except Exception:
        # If DNS fails, treat as unsafe
        raise ValueError("Could not resolve hostname safely")

    # Return normalized URL (strip fragments)
    return p._replace(fragment="").geturl()


async def fetch_public_page_text(url: str, max_chars: int = 200_000) -> str:
    """
    Fetch HTML from a public page with strict limits.
    """
    safe_url = _safe_http_url(url)
    headers = {
        "User-Agent": "AIWidgetBot/1.0 (+https://example.com)",
        "Accept": "text/html,application/xhtml+xml",
    }
    timeout = httpx.Timeout(6.0, connect=4.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(safe_url, headers=headers)
        if r.status_code >= 400:
            raise ValueError(f"Website returned {r.status_code}")
        text = r.text or ""
        return text[:max_chars]


def extract_signals_from_html(html: str) -> Dict[str, Any]:
    """
    Very light HTML -> text extraction (no external libs).
    """
    # title
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<.*?>", "", m.group(1))).strip()

    # meta description
    desc = ""
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.I | re.S)
    if m:
        desc = re.sub(r"\s+", " ", m.group(1)).strip()

    # headings + body text (rough)
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", cleaned)
    text = re.sub(r"(?s)<.*?>", " ", cleaned)
    text = re.sub(r"\s+", " ", text).strip()

    # Grab a small chunk for keywording
    snippet = text[:6000]

    return {
        "title": title,
        "description": desc,
        "snippet": snippet,
    }


# --------------------------------------------------
# AUTH + DOMAIN LOCKING
# --------------------------------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "").strip()
    origin = (request.headers.get("origin") or "").lower()

    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed = data.get("domains", [])
            if allowed and "*" not in allowed:
                if not any(d.lower() in origin for d in allowed):
                    raise HTTPException(status_code=403, detail="Domain not allowed for this API key")
            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")


# --------------------------------------------------
# RANKING LOGIC (heuristic scoring + reasons)
# --------------------------------------------------
SERVICE_LIBRARY = [
    {
        "service": "Website copywriting",
        "keywords": ["copy", "headline", "messaging", "positioning", "brand voice", "landing page"],
        "fits_goals": ["leads", "lead generation", "conversion", "sales"],
    },
    {
        "service": "Landing page creation",
        "keywords": ["landing", "conversion", "cta", "signup", "book a call", "funnel"],
        "fits_goals": ["leads", "lead generation", "conversion", "sales"],
    },
    {
        "service": "SEO optimization",
        "keywords": ["seo", "search", "keywords", "ranking", "google", "organic traffic"],
        "fits_goals": ["traffic", "leads", "growth"],
    },
    {
        "service": "Lead funnel optimization",
        "keywords": ["crm", "pipeline", "funnel", "lead", "automation", "forms"],
        "fits_goals": ["leads", "lead generation", "conversion"],
    },
    {
        "service": "Paid ads setup",
        "keywords": ["google ads", "meta ads", "facebook ads", "ppc", "paid search"],
        "fits_goals": ["leads", "sales", "growth"],
    },
    {
        "service": "Email nurture sequence",
        "keywords": ["email", "newsletter", "nurture", "drip", "automation"],
        "fits_goals": ["leads", "conversion", "retention"],
    },
]

OFFERING_HINTS = [
    # If the site already mentions these, we avoid recommending as strongly
    ("seo", "SEO optimization"),
    ("paid ads", "Paid ads setup"),
    ("google ads", "Paid ads setup"),
    ("facebook ads", "Paid ads setup"),
    ("copywriting", "Website copywriting"),
    ("landing page", "Landing page creation"),
    ("email marketing", "Email nurture sequence"),
]


def _contains(text: str, word: str) -> bool:
    return word.lower() in (text or "").lower()


def rank_services(
    industry: str,
    goal: str,
    target_signals: Dict[str, Any],
    embed_signals: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Produce [{service, score, why}] using simple keyword heuristics.
    """
    industry_l = (industry or "").lower()
    goal_l = (goal or "").lower()

    corpus = " ".join(
        [
            target_signals.get("title", ""),
            target_signals.get("description", ""),
            target_signals.get("snippet", ""),
            embed_signals.get("title", ""),
            embed_signals.get("description", ""),
            embed_signals.get("snippet", ""),
        ]
    ).lower()

    # Detect what services the company already offers (based on embed site / target site mentions)
    already_offers = set()
    for hint_word, service_name in OFFERING_HINTS:
        if hint_word in corpus:
            already_offers.add(service_name)

    results = []
    for item in SERVICE_LIBRARY:
        service = item["service"]
        score = 30  # base
        reasons = []

        # Industry boost
        if "marketing" in industry_l or "agency" in industry_l:
            score += 10
            reasons.append("Industry suggests marketing-led growth.")

        # Goal match boost
        if any(g in goal_l for g in item["fits_goals"]):
            score += 25
            reasons.append(f"Matches your goal: “{goal}”.")

        # Keyword matches in website content
        hits = 0
        for kw in item["keywords"]:
            if kw.lower() in corpus:
                hits += 1
        if hits:
            score += min(25, hits * 6)
            reasons.append("Website content indicates this would be impactful.")

        # If they already offer it, lower score (still may recommend, but less)
        if service in already_offers:
            score -= 18
            reasons.append("Your website already mentions offering something similar.")

        # Clamp
        score = max(5, min(99, score))

        why = " ".join(reasons) if reasons else "Based on the inputs provided."
        results.append({"service": service, "score": score, "why": why})

    # Sort high->low and take top 5
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]


# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recommend")
async def recommend(
    data: RequestData,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    client = verify_api_key(authorization, request)

    # 1) Analyze the URL the user typed (website_url)
    target_signals = {"title": "", "description": "", "snippet": ""}
    target_error = ""
    try:
        html = await fetch_public_page_text(data.website_url)
        target_signals = extract_signals_from_html(html)
    except Exception as e:
        target_error = str(e)

    # 2) Analyze the page where widget is embedded (Origin header)
    origin = request.headers.get("origin") or ""
    embed_signals = {"title": "", "description": "", "snippet": ""}
    embed_error = ""
    try:
        if origin:
            html2 = await fetch_public_page_text(origin)
            embed_signals = extract_signals_from_html(html2)
    except Exception as e:
        embed_error = str(e)

    ranked = rank_services(
        industry=data.industry,
        goal=data.goal,
        target_signals=target_signals,
        embed_signals=embed_signals,
    )

    response = {
        "client": client,
        "branding": API_KEYS.get(client, {}).get("branding", None),
        "ranked_services": ranked,  # ✅ widget can render rings + "Why these?"
        "debug": {
            "origin": origin,
            "target_fetch_error": target_error,
            "embed_fetch_error": embed_error,
        },
    }
    return response


@app.get("/usage/me")
def usage_me(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    client = verify_api_key(authorization, request)
    return {"client": client, "usage": USAGE_COUNTER[client]}
