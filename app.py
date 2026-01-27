from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from collections import defaultdict
from urllib.parse import urlparse

app = FastAPI(title="AI Widget Backend")

# -----------------------------
# CORS (lock later per domain)
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: lock per customer
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# API KEYS + DOMAIN LOCKING + BRANDING
# -----------------------------
API_KEYS: Dict[str, Dict[str, Any]] = {
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
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "usage": 0,
        "branding": {
            "name": "Acme",
            "logo_url": "",
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
}

USAGE_COUNTER = defaultdict(int)

# -----------------------------
# DATA MODEL (✅ matches widget payload)
# -----------------------------
class RequestData(BaseModel):
    website_url: str
    industry: str
    goal: str

# -----------------------------
# HELPERS
# -----------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format (use Bearer)")

    key = authorization.replace("Bearer ", "").strip()

    for client, data in API_KEYS.items():
        if key == data["key"]:
            origin = (request.headers.get("origin") or "").lower()
            allowed_domains = [d.lower() for d in data["domains"]]

            # Domain allow
            if "*" not in allowed_domains:
                if not any(domain in origin for domain in allowed_domains):
                    raise HTTPException(status_code=403, detail="Domain not allowed for this API key")

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")


def host_from_url(url: str) -> str:
    try:
        p = urlparse(url if "://" in url else "https://" + url)
        return (p.netloc or "").lower()
    except:
        return ""


def ranked_recommendations(website_url: str, industry: str, goal: str) -> List[Dict[str, Any]]:
    industry_l = (industry or "").lower()
    goal_l = (goal or "").lower()
    host = host_from_url(website_url)

    items: List[Dict[str, Any]] = []

    # Simple scoring rules (you can swap for GPT later)
    def add(service: str, score: int, why: str):
        items.append({"service": service, "score": max(0, min(100, score)), "why": why})

    if "marketing" in industry_l:
        add("Landing page creation", 85, "Marketing-focused businesses convert better with dedicated landing pages.")
        add("SEO optimization", 78, "SEO helps capture ongoing intent-based traffic from Google.")
        add("Website copywriting", 72, "Clear messaging improves conversion rate and lead quality.")

    if "lead" in goal_l:
        add("Lead funnel optimization", 88, "Your goal is leads — tightening the funnel increases conversion.")
        add("Offer + CTA audit", 74, "Improving the offer and CTA usually lifts leads quickly.")

    # Website-url hints (lightweight)
    if host and ("shop" in host or "store" in host):
        add("Conversion rate optimization", 80, "Your URL looks commerce-related — CRO boosts signups/sales.")

    # If nothing matched, still return something useful
    if not items:
        add("Website copywriting", 70, "A strong baseline improvement for most websites.")
        add("Landing page creation", 65, "A focused page helps align your goal with conversions.")
        add("SEO optimization", 60, "Improves discoverability over time.")

    # Deduplicate by service (keep highest score)
    best = {}
    for it in items:
        name = it["service"]
        if name not in best or it["score"] > best[name]["score"]:
            best[name] = it

    ranked = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:6]

# -----------------------------
# ROUTES
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/recommend")
def recommend(
    data: RequestData,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    client = verify_api_key(authorization, request)

    ranked = ranked_recommendations(
        website_url=data.website_url,
        industry=data.industry,
        goal=data.goal,
    )

    return {
        "client": client,
        "branding": API_KEYS[client].get("branding", None),
        "ranked_services": ranked,  # ✅ what widget expects
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)

