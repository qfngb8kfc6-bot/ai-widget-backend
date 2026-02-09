from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from collections import defaultdict

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
# API KEYS + DOMAIN LOCKING + BRANDING (optional)
# --------------------------------------------------
API_KEYS: Dict[str, Dict[str, Any]] = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "usage": 0,
        "branding": {
            "name": "Acme AI",
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
            "logo_url": ""
        }
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
        "usage": 0,
        "branding": {
            "name": "AI Widget",
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
            "logo_url": ""
        }
    }
}

# Usage tracking (in-memory for now)
USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL (matches your widget: website_url + industry + goal + host_url)
# --------------------------------------------------
class RecommendRequest(BaseModel):
    website_url: str
    industry: str
    goal: str
    host_url: Optional[str] = ""  # widget host page URL (sent from widget)

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> str:
    """
    Verifies Bearer API key and checks Origin domain against allowed domains.
    Returns client name.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format (expected Bearer ...)")

    key = authorization.replace("Bearer ", "").strip()

    for client, data in API_KEYS.items():
        if key == data["key"]:
            origin = (request.headers.get("origin") or "").lower()
            allowed_domains = [d.lower() for d in data.get("domains", [])]

            # Domain check (simple substring match)
            if "*" not in allowed_domains and origin:
                if not any(domain in origin for domain in allowed_domains):
                    raise HTTPException(
                        status_code=403,
                        detail="Domain not allowed for this API key",
                    )

            USAGE_COUNTER[client] += 1
            data["usage"] = int(data.get("usage", 0)) + 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")

def recommend_ranked(industry: str, goal: str) -> List[Dict[str, Any]]:
    """
    Simple ranked recommendations with scores + why.
    Replace this later with your real website/host scanning logic.
    """
    industry_l = (industry or "").lower()
    goal_l = (goal or "").lower()

    ranked = []

    # Base candidates
    candidates = [
        ("SEO optimization", 0, "Improves organic visibility and leads over time."),
        ("Website copywriting", 0, "Clarifies your message and increases conversions."),
        ("Content marketing", 0, "Builds trust and attracts your ideal customers consistently."),
        ("Landing page creation", 0, "Converts traffic into leads with focused pages."),
        ("Lead funnel optimization", 0, "Improves conversion rates from visit → lead → customer."),
    ]

    # Score rules
    for service, score, why in candidates:
        s = score

        if "marketing" in industry_l:
            if service in ("SEO optimization", "Website copywriting", "Content marketing", "Landing page creation"):
                s += 35
                why = "Your industry suggests marketing-led growth opportunities."

        if any(x in goal_l for x in ["lead", "leads", "lead generation", "pipeline", "sales"]):
            if service in ("Landing page creation", "Lead funnel optimization", "Website copywriting"):
                s += 35
                why = "Your goal indicates you need more qualified leads and conversions."

        if any(x in goal_l for x in ["brand", "awareness", "visibility"]):
            if service in ("Content marketing", "SEO optimization"):
                s += 25
                why = "Your goal suggests increasing awareness and discoverability."

        # Keep only meaningful suggestions
        if s > 0:
            ranked.append({"service": service, "score": min(95, s), "why": why})

    # If nothing matched, return a safe default set
    if not ranked:
        ranked = [
            {"service": "Website audit", "score": 60, "why": "A quick audit reveals the highest-impact improvements."},
            {"service": "Landing page creation", "score": 55, "why": "A focused page can increase conversions quickly."},
            {"service": "SEO optimization", "score": 50, "why": "Improves visibility and compounding growth over time."},
        ]

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:5]

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
    authorization: Optional[str] = Header(None),
):
    client = verify_api_key(authorization, request)

    ranked_services = recommend_ranked(
        industry=data.industry,
        goal=data.goal,
    )

    # Keep backward compatibility too (widget might still read recommended_services)
    recommended_services = [r["service"] for r in ranked_services]

    branding = API_KEYS.get(client, {}).get("branding") or None

    return {
        "client": client,
        "branding": branding,
        "recommended_services": recommended_services,
        "ranked_services": ranked_services,
        "inputs": {
            "website_url": data.website_url,
            "host_url": data.host_url,
            "industry": data.industry,
            "goal": data.goal,
        },
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    _ = verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)

# --------------------------------------------------
# Swagger/OpenAPI: Add Authorize button for Bearer keys
# --------------------------------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version="1.0.0",
        description="AI Widget Backend",
        routes=app.routes,
    )

    openapi_schema.setdefault("components", {})
    openapi_schema["components"].setdefault("securitySchemes", {})
    openapi_schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API Key",
    }

    # Apply globally so Swagger UI uses it
    openapi_schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

