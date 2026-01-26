from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
from collections import defaultdict
from urllib.parse import urlparse

app = FastAPI(title="AI Widget Backend")

# --------------------------------------------------
# CORS (allow widget + GitHub Pages)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can lock later
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
        "usage": 0,
        "branding": {
            "name": "Acme",
            "logo_url": "https://via.placeholder.com/120x32?text=ACME",
            "primary": "#0b1020",     # button
            "grad1": "#1e50a0",       # pill gradient left
            "grad2": "#28aabe",       # pill gradient right
        },
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
        "usage": 0,
        "branding": {
            "name": "Demo",
            "logo_url": "",           # optional
            "primary": "#0b1020",
            "grad1": "#1e50a0",
            "grad2": "#28aabe",
        },
    },
}

USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL (matches widget.js payload)
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: str
    industry: str
    goal: str

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def _get_origin_host(request: Request) -> str:
    origin = request.headers.get("origin", "") or ""
    if not origin:
        return ""
    try:
        return urlparse(origin).hostname or origin
    except Exception:
        return origin

def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "", 1).strip()
    origin_host = _get_origin_host(request)

    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed = data.get("domains", [])

            # If you ever want to allow all: ["*"]
            if "*" not in allowed and allowed:
                # If origin is missing (some clients/tools), block by default:
                if not origin_host:
                    raise HTTPException(status_code=403, detail="Missing Origin header")
                if not any(origin_host.endswith(d) or origin_host == d for d in allowed):
                    raise HTTPException(status_code=403, detail="Domain not allowed for this API key")

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")

def recommend_services(industry: str, goal: str):
    recs = []

    if "marketing" in industry.lower():
        recs += ["Website copywriting", "Landing page creation", "SEO optimization"]

    if goal.lower() in ["lead generation", "leads", "more leads"]:
        recs.append("Lead funnel optimization")

    if "sales" in goal.lower():
        recs.append("Sales enablement assets")

    # unique
    return list(dict.fromkeys(recs))

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

    services = recommend_services(data.industry, data.goal)
    branding = API_KEYS.get(client, {}).get("branding", {})

    return {
        "client": client,
        "branding": branding,  # 👈 key part
        "recommended_services": services,
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    # Require a valid key to view usage (or restrict to admin keys later)
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)
