from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, AnyHttpUrl
from typing import Optional, Dict, List, Any
from collections import defaultdict
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

app = FastAPI(title="AI Widget Backend")

# --------------------------------------------------
# CORS (keep open while testing; lock later)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock later per domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING + BRANDING
# --------------------------------------------------
# NOTE: This is in-memory demo storage. For real SaaS, move to DB.
API_KEYS: Dict[str, Dict[str, Any]] = {
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],  # allow GitHub Pages + local
        "branding": {
            "name": "Tamed AI",
            "logo_url": "",  # optional
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "branding": {
            "name": "Acme",
            "logo_url": "",
            "primary": "#0b1020",
            "grad1": "#7c3aed",
            "grad2": "#22c55e",
        },
    },
}

USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# REQUEST MODEL
# --------------------------------------------------
class RecommendRequest(BaseModel):
    website_url: AnyHttpUrl
    host_url: AnyHttpUrl
    industry: str
    goal: str

# --------------------------------------------------
# HELPERS: auth + domain lock
# --------------------------------------------------
def _extract_hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""

def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "").strip()

    # Origin is best for browser calls; Referer can be fallback
    origin = request.headers.get("origin", "") or ""
    referer = request.headers.get("referer", "") or ""

    origin_host = _extract_hostname(origin)
    referer_host = _extract_hostname(referer)

    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed = data.get("domains", [])

            # If allowed contains "*", skip checks (not recommended)
            if "*" not in allowed:
                # if no origin (some tools/curl), allow
                if origin_host or referer_host:
                    # allow if either matches
                    ok = any(
                        (d in origin_host) or (d in referer_host)
                        for d in allowed
                    )
                    if not ok:
                        raise HTTPException(
                            status_code=403,
                            detail="Domain not allowed for this API key",
                        )

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")

# --------------------------------------------------
# WEBSITE FETCH + TEXT EXTRACTION
# --------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

async def fetch_html(url: str) -> str:
    # IMPORTANT: some sites block scraping. This is a basic MVP.
    timeout = httpx.Timeout(12.0, connect=8.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # remove junk
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = " ".join(soup.stripped_strings)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text

# --------------------------------------------------
# SERVICE TAXONOMY (MVP)
# --------------------------------------------------
# This is intentionally opinionated and small to keep it stable.
SERVICES: Dict[str, List[str]] = {
    "SEO optimisation": ["seo", "search engine", "google ranking", "keyword", "backlink", "technical seo"],
    "Paid ads (PPC)": ["ppc", "google ads", "meta ads", "facebook ads", "paid search", "paid social"],
    "Landing pages & CRO": ["landing page", "conversion", "cro", "a/b test", "funnel", "lead funnel"],
    "Website copywriting": ["copywriting", "website copy", "messaging", "headline", "value proposition"],
    "Content marketing": ["content", "blog", "articles", "editorial", "content strategy"],
    "Email marketing": ["email marketing", "newsletter", "crm", "mailchimp", "klaviyo", "automation"],
    "Brand & positioning": ["brand", "positioning", "identity", "tone of voice", "rebrand"],
    "Social media marketing": ["social media", "instagram", "linkedin", "tiktok", "community", "social strategy"],
    "Web design & build": ["web design", "ux", "ui", "website redesign", "wordpress", "webflow", "shopify"],
    "Analytics & tracking": ["analytics", "ga4", "tracking", "pixels", "tag manager", "attribution"],
}

# Goal → boosters (MVP)
GOAL_BOOST: Dict[str, List[str]] = {
    "lead": ["Landing pages & CRO", "Paid ads (PPC)", "SEO optimisation", "Email marketing"],
    "sales": ["Paid ads (PPC)", "Landing pages & CRO", "Email marketing", "Analytics & tracking"],
    "traffic": ["SEO optimisation", "Content marketing", "Social media marketing", "Paid ads (PPC)"],
    "brand": ["Brand & positioning", "Content marketing", "Social media marketing", "Website copywriting"],
}

def keyword_hits(text: str, keywords: List[str]) -> int:
    hits = 0
    for k in keywords:
        # simple contains count; good enough for MVP
        hits += text.count(k)
    return hits

def compute_ranked_services(
    client_text: str,
    host_text: str,
    industry: str,
    goal: str
) -> List[Dict[str, Any]]:
    """
    Strategy (MVP):
    - Determine what the client likely needs from their site text + industry + goal
    - Determine what the host likely offers from host site text
    - Score = need_score + offer_score + goal_boost
    - Explain "why" with evidence
    """

    goal_l = goal.lower()
    industry_l = industry.lower()

    # which services are boosted by goal keywords
    boosted_services = set()
    for gkey, services in GOAL_BOOST.items():
        if gkey in goal_l:
            boosted_services.update(services)

    ranked = []
    for service, keys in SERVICES.items():
        # Evidence: client needs
        need = keyword_hits(client_text, keys)
        # Evidence: host offerings
        offer = keyword_hits(host_text, keys)

        # Industry bump (tiny heuristic)
        industry_bump = 2 if any(w in industry_l for w in ["marketing", "agency", "ecommerce", "saas", "software"]) else 0

        # Goal bump
        goal_bump = 8 if service in boosted_services else 0

        # If host offers it, we prefer it (you asked: host services)
        offer_weighted = offer * 2
        need_weighted = need * 1

        raw = offer_weighted + need_weighted + goal_bump + industry_bump

        # If absolutely no signal, skip (keeps results clean)
        if raw <= 0:
            continue

        # Create explanation
        why_parts = []
        if offer > 0:
            why_parts.append("Host site appears to mention this service.")
        else:
            why_parts.append("Host site does not clearly mention this, but it may still be a good fit.")

        if need > 0:
            why_parts.append("Client site content suggests relevance (keywords found).")
        else:
            why_parts.append("Client site content did not strongly signal this; goal/industry may drive the fit.")

        if goal_bump > 0:
            why_parts.append(f"Matches the goal: “{goal}”.")

        score = raw  # we'll normalize to 0–100 later
        ranked.append(
            {
                "service": service,
                "raw": score,
                "why": " ".join(why_parts),
                "need_hits": need,
                "offer_hits": offer,
            }
        )

    if not ranked:
        return []

    # Normalize raw scores to 0–100
    max_raw = max(r["raw"] for r in ranked) or 1
    for r in ranked:
        r["score"] = int(round((r["raw"] / max_raw) * 100))
        # clean fields the widget expects
        del r["raw"]

    ranked.sort(key=lambda x: x["score"], reverse=True)

    # keep top 6 to look SaaS-y
    return ranked[:6]

# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/recommend")
async def recommend(
    data: RecommendRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    client = verify_api_key(authorization, request)
    branding = API_KEYS.get(client, {}).get("branding", None)

    # Fetch BOTH sites
    try:
        client_html = await fetch_html(str(data.website_url))
        host_html = await fetch_html(str(data.host_url))
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch one of the websites: {str(e)}",
        )

    client_text = html_to_text(client_html)
    host_text = html_to_text(host_html)

    ranked_services = compute_ranked_services(
        client_text=client_text,
        host_text=host_text,
        industry=data.industry,
        goal=data.goal,
    )

    return {
        "client": client,
        "branding": branding,
        "ranked_services": ranked_services,  # <-- THIS is what your widget should render
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    # must verify correctly using actual request object
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)
