from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Tuple
from collections import defaultdict
from urllib.parse import urlparse
import re
import time

app = FastAPI(title="AI Widget Backend")

# --------------------------------------------------
# CORS
# NOTE: You can lock this down later. For now allow all.
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        "domains": ["acme.com"],  # allowed Origins
        "branding": {
            "name": "ACME",
            "logo_url": "",
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
# DATA MODEL (MATCHES YOUR WIDGET)
# --------------------------------------------------
class RecommendRequest(BaseModel):
    website_url: str = Field(..., description="Customer website URL")
    industry: str = Field(..., description="Industry")
    goal: str = Field(..., description="Goal")


# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def _origin_host(origin: str) -> str:
    """
    origin may be like:
      https://qfngb8kfc6-bot.github.io
      http://localhost:5500
    """
    if not origin:
        return ""
    try:
        parsed = urlparse(origin)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def _domain_allowed(origin_host: str, allowed_domains: List[str]) -> bool:
    if not origin_host:
        return False

    # allow wildcard if ever used
    if "*" in allowed_domains:
        return True

    for d in allowed_domains:
        d = d.lower().strip()
        if not d:
            continue
        # allow exact host OR subdomain
        # e.g. origin_host = "www.acme.com" allowed "acme.com"
        if origin_host == d or origin_host.endswith("." + d) or origin_host.endswith(d):
            return True
    return False


def verify_api_key(authorization: Optional[str], request: Request) -> Tuple[str, Dict[str, Any]]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format (use Bearer)")

    key = authorization.replace("Bearer ", "").strip()
    origin = request.headers.get("origin", "")
    origin_host = _origin_host(origin)

    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed_domains = data.get("domains", [])

            # domain lock
            if allowed_domains:
                if not _domain_allowed(origin_host, allowed_domains):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Domain not allowed for this API key (origin: {origin_host or 'none'})",
                    )

            USAGE_COUNTER[client] += 1
            return client, data

    raise HTTPException(status_code=403, detail="Invalid API key")


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def recommend_services(website_url: str, industry: str, goal: str) -> List[Dict[str, Any]]:
    """
    Heuristic scoring (no external scraping required).
    Returns ranked recommendations with scores + reasons.
    """
    industry_l = _clean_text(industry)
    goal_l = _clean_text(goal)
    site_l = _clean_text(website_url)

    catalog = [
        ("Website copywriting", ["marketing", "agency", "ecommerce", "saas", "brand"]),
        ("Landing page creation", ["lead", "conversion", "campaign", "marketing", "ads"]),
        ("SEO optimization", ["seo", "organic", "search", "content", "blog", "marketing"]),
        ("Paid ads (Google/Meta)", ["ads", "ppc", "paid", "leads", "conversion"]),
        ("Lead funnel optimization", ["lead", "leads", "generation", "funnel", "pipeline"]),
        ("Email nurture automation", ["email", "crm", "retention", "lifecycle", "newsletter"]),
        ("Analytics & tracking setup", ["analytics", "tracking", "attribution", "ga4", "events"]),
    ]

    # keyword signals
    signals = set()
    for token in re.findall(r"[a-z0-9]+", f"{industry_l} {goal_l} {site_l}"):
        signals.add(token)

    scored = []
    for service, keys in catalog:
        score = 20  # base

        # boost based on industry keywords
        for k in keys:
            if k in industry_l:
                score += 18
            if k in goal_l:
                score += 22
            if k.replace(" ", "") in site_l.replace(" ", ""):
                score += 8

        # special boosts
        if "lead" in goal_l or "leads" in goal_l or "lead generation" in goal_l:
            if service in ("Landing page creation", "Lead funnel optimization", "Paid ads (Google/Meta)"):
                score += 20

        if "seo" in goal_l or "organic" in goal_l:
            if service == "SEO optimization":
                score += 25

        if "ecommerce" in industry_l or "shop" in site_l:
            if service in ("SEO optimization", "Paid ads (Google/Meta)", "Analytics & tracking setup"):
                score += 15

        score = max(0, min(100, score))
        scored.append((service, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    # top 3-5
    top = scored[:5]

    recommendations = []
    for service, score in top:
        why_bits = []
        if score >= 80:
            why_bits.append("Strong match to your inputs")
        if "lead" in goal_l and service in ("Landing page creation", "Lead funnel optimization", "Paid ads (Google/Meta)"):
            why_bits.append("Optimized for lead generation")
        if "marketing" in industry_l and service in ("Website copywriting", "SEO optimization", "Landing page creation"):
            why_bits.append("Commonly effective for marketing-driven businesses")
        if not why_bits:
            why_bits.append("Relevant based on industry + goal")

        recommendations.append({
            "service": service,
            "score": score,   # 0-100
            "why": ". ".join(why_bits) + ".",
        })

    return recommendations


# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recommend")
def recommend(
    data: RecommendRequest,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    client, client_data = verify_api_key(authorization, request)

    recs = recommend_services(
        website_url=data.website_url,
        industry=data.industry,
        goal=data.goal
    )

    # Backwards compatible simple list:
    recommended_services = [r["service"] for r in recs]

    return {
        "client": client,
        "branding": client_data.get("branding", {}),
        "recommended_services": recommended_services,
        "recommendations": recs,  # ranked with score + why
        "usage": USAGE_COUNTER[client],
        "ts": int(time.time()),
    }


@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    client, _ = verify_api_key(authorization, request)
    return {"client": client, "usage": USAGE_COUNTER[client]}
