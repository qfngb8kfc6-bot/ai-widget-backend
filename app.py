from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any, List
from collections import defaultdict
import re

import httpx
from bs4 import BeautifulSoup

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
# API KEYS + DOMAIN LOCKING + (optional) BRANDING
# --------------------------------------------------
API_KEYS: Dict[str, Dict[str, Any]] = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "usage": 0,
        "branding": {
            "name": "Acme AI",
            "logo_url": "",
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
        "usage": 0,
        "branding": {
            "name": "AI Widget",
            "logo_url": "",
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
}

USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL (matches your widget: website_url + industry + goal)
# host_url is optional but recommended (widget should send it)
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: HttpUrl
    industry: str
    goal: str
    host_url: Optional[HttpUrl] = None


# --------------------------------------------------
# HELPERS: API KEY + DOMAIN LOCK
# --------------------------------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "").strip()

    for client, data in API_KEYS.items():
        if key == data["key"]:
            origin = request.headers.get("origin", "") or ""
            allowed_domains = data.get("domains", ["*"])

            if "*" not in allowed_domains:
                if not any(domain in origin for domain in allowed_domains):
                    raise HTTPException(
                        status_code=403,
                        detail="Domain not allowed for this API key",
                    )

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")


# --------------------------------------------------
# WEBSITE FETCHING + TEXT EXTRACTION
# IMPORTANT: This is where the 403 can happen.
# We DO NOT fail the whole request anymore.
# --------------------------------------------------
async def fetch_html(url: str) -> str:
    # A realistic browser-ish user agent helps reduce blocks (not perfect)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    timeout = httpx.Timeout(12.0, connect=8.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.text


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Remove junk
    for tag in soup(["script", "style", "noscript", "svg", "img", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# --------------------------------------------------
# "What services does host offer?" (very simple keyword extraction)
# You can expand this later.
# --------------------------------------------------
SERVICE_KEYWORDS = {
    "SEO optimization": ["seo", "search engine optimization"],
    "Website copywriting": ["copywriting", "copywriter", "website copy"],
    "Landing page creation": ["landing page", "conversion page"],
    "Google Ads / PPC": ["ppc", "google ads", "paid search", "adwords"],
    "Social media management": ["social media", "instagram", "facebook", "tiktok", "linkedin"],
    "Email marketing": ["email marketing", "newsletter", "mailchimp", "klaviyo"],
    "Brand strategy": ["brand strategy", "branding", "positioning"],
    "Web design": ["web design", "ui", "ux", "website design"],
    "Web development": ["web development", "development", "react", "wordpress", "shopify"],
    "Lead funnel optimization": ["lead funnel", "conversion rate", "cro", "funnel"],
    "Content marketing": ["content marketing", "blog", "articles", "content strategy"],
}

def extract_host_services(host_text: str) -> List[str]:
    if not host_text:
        return []

    t = host_text.lower()
    found = []
    for service, kws in SERVICE_KEYWORDS.items():
        if any(kw in t for kw in kws):
            found.append(service)

    # limit noise
    return found[:10]


# --------------------------------------------------
# RECOMMENDATION ENGINE (ranked services with % + why)
# This uses:
# - industry + goal (always)
# - client site text (if available)
# - host site services (if available)
# --------------------------------------------------
def recommend_ranked(industry: str, goal: str, client_text: str, host_services: List[str]) -> List[Dict[str, Any]]:
    industry_l = (industry or "").lower()
    goal_l = (goal or "").lower()
    client_l = (client_text or "").lower()

    candidates = set()

    # Base candidates from industry/goal
    if "marketing" in industry_l:
        candidates.update(["SEO optimization", "Website copywriting", "Landing page creation", "Content marketing"])
        candidates.update(["Social media management", "Email marketing", "Google Ads / PPC"])

    if any(g in goal_l for g in ["lead", "leads", "lead generation", "pipeline", "sales"]):
        candidates.update(["Lead funnel optimization", "Landing page creation", "Google Ads / PPC", "Email marketing"])

    if any(g in goal_l for g in ["brand", "branding", "awareness"]):
        candidates.update(["Brand strategy", "Content marketing", "Social media management", "Website copywriting"])

    # Add services found on host site (if available)
    for s in host_services:
        candidates.add(s)

    # If we still have nothing, provide a safe default set
    if not candidates:
        candidates.update(["SEO optimization", "Landing page creation", "Website copywriting"])

    ranked = []

    def contains_any(text: str, keywords: List[str]) -> bool:
        return any(k in text for k in keywords)

    for service in candidates:
        score = 0
        reasons = []

        # Industry/goal weighting
        if service in ["SEO optimization", "Content marketing", "Website copywriting"]:
            if "marketing" in industry_l:
                score += 25
                reasons.append("Your industry suggests marketing-led growth opportunities.")

        if service in ["Lead funnel optimization", "Landing page creation", "Google Ads / PPC", "Email marketing"]:
            if any(g in goal_l for g in ["lead", "leads", "lead generation", "pipeline", "sales"]):
                score += 35
                reasons.append("Your goal indicates you want more leads, so conversion and acquisition matter most.")

        if service in ["Brand strategy", "Social media management", "Content marketing"]:
            if any(g in goal_l for g in ["brand", "branding", "awareness"]):
                score += 35
                reasons.append("Your goal focuses on awareness, so brand + content channels are key.")

        # Boost if host already offers this service
        if service in host_services:
            score += 20
            reasons.append("The host site appears to offer this service already (good fit to propose).")

        # Boost if client website text contains related words
        kws = SERVICE_KEYWORDS.get(service, [])
        if client_l and kws and contains_any(client_l, kws):
            score += 20
            reasons.append("Your website content hints this service is relevant to your current offering or messaging.")

        # Small baseline so we always return something sensible
        score += 10

        # Cap score 0-100
        score = max(0, min(100, score))

        # Filter out ultra-low junk
        if score < 20:
            continue

        ranked.append({
            "service": service,
            "score": score,
            "why": " ".join(reasons) if reasons else "Based on your industry and goal."
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)

    # Return top 6
    return ranked[:6]


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

    # --- NEW: DO NOT FAIL if scraping fails ---
    client_text = ""
    host_text = ""

    # Try client website (entered url)
    try:
        client_html = await fetch_html(str(data.website_url))
        client_text = html_to_text(client_html)
    except Exception:
        # blocked/403/timeouts/etc -> just continue
        client_text = ""

    # Try host site (where widget is embedded)
    # If host_url not provided, fallback to Origin header (best effort)
    host_url = str(data.host_url) if data.host_url else (request.headers.get("origin") or "")
    if host_url:
        try:
            host_html = await fetch_html(host_url)
            host_text = html_to_text(host_html)
        except Exception:
            host_text = ""

    host_services = extract_host_services(host_text)

    ranked = recommend_ranked(
        industry=data.industry,
        goal=data.goal,
        client_text=client_text,
        host_services=host_services,
    )

    branding = API_KEYS.get(client, {}).get("branding", None)

    return {
        "client": client,
        "branding": branding,
        "ranked_services": ranked,  # <-- widget should read this
        "host_services_detected": host_services,  # helpful for debugging
        "signals": {
            "client_site_scraped": bool(client_text),
            "host_site_scraped": bool(host_text),
        },
    }


@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    # verify_api_key needs a real request object (this function has it)
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)

