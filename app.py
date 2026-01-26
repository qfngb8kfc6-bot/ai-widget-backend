from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
from collections import defaultdict
from urllib.parse import urlparse

app = FastAPI(title="AI Widget Backend")

# --------------------------------------------------
# CORS (keep open for now; domain-lock happens in verify_api_key)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING (edit these)
# --------------------------------------------------
API_KEYS: Dict[str, Dict[str, Any]] = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],     # allowed origins must contain one of these
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],  # allows GitHub Pages + local dev
    },
}

# Usage tracking (in-memory)
USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL (matches your widget now)
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: str
    industry: str
    goal: str

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def _origin_host(origin: str) -> str:
    """
    Convert an Origin header like 'https://qfngb8kfc6-bot.github.io'
    into a host like 'qfngb8kfc6-bot.github.io'
    """
    if not origin:
        return ""
    try:
        parsed = urlparse(origin)
        return parsed.netloc or origin
    except Exception:
        return origin

def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format (use: Bearer <key>)")

    key = authorization.replace("Bearer ", "").strip()

    origin = request.headers.get("origin", "")
    host = _origin_host(origin)

    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed_domains = data.get("domains", [])

            # Domain lock
            if allowed_domains and "*" not in allowed_domains:
                if not any(d in host for d in allowed_domains):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Domain not allowed for this API key (origin: {origin})",
                    )

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")

def recommend_services(industry: str, goal: str):
    recommendations = []

    if "marketing" in industry.lower():
        recommendations.extend([
            "Website copywriting",
            "Landing page creation",
            "SEO optimization",
        ])

    if goal.lower() in ["lead generation", "leads", "more leads"]:
        recommendations.append("Lead funnel optimization")

    if "ecommerce" in industry.lower():
        recommendations.append("Conversion rate optimization")

    # de-dupe
    return list(dict.fromkeys(recommendations))

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
    authorization: Optional[str] = Header(None),
):
    client = verify_api_key(authorization, request)

    services = recommend_services(
        data.industry,
        data.goal,
    )

    return {
        "client": client,
        "recommended_services": services,
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    # Only allow valid keys to view usage
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)
