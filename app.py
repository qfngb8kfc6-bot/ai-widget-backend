from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, List
from collections import defaultdict
from urllib.parse import urlparse

app = FastAPI(title="AI Widget Backend")

# --------------------------------------------------
# CORS (keep open while testing; lock later)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later: set this to your allowed customer origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # includes Authorization for Bearer token
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING
# --------------------------------------------------
API_KEYS: Dict[str, Dict[str, object]] = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],   # allow acme.com + *.acme.com
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],  # allow localhost + any github.io subdomain
    },
}

# In-memory usage tracking (resets on deploy/restart)
USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL (matches your widget)
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: Optional[str] = ""
    industry: str
    goal: str

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def _origin_host(origin: str) -> str:
    """
    Extract hostname from Origin header (e.g. https://sub.example.com -> sub.example.com)
    """
    if not origin:
        return ""
    try:
        parsed = urlparse(origin)
        return parsed.hostname or ""
    except Exception:
        return ""

def _domain_allowed(host: str, allowed_domains: List[str]) -> bool:
    """
    Allow:
      - exact domain match (example.com)
      - subdomain match (*.example.com)
      - simple contains for localhost during dev if needed
    """
    if not host:
        return False

    for d in allowed_domains:
        d = d.strip().lower()
        h = host.lower()

        # exact match
        if h == d:
            return True

        # allow subdomains: foo.example.com endswith .example.com
        if h.endswith("." + d):
            return True

    return False

def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key (Authorization header)")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format. Use: Bearer <key>")

    key = authorization.replace("Bearer ", "").strip()

    origin = request.headers.get("origin", "")
    host = _origin_host(origin)

    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed_domains = data.get("domains", [])

            # If you want to allow any domain for some keys, add "*" to their domains list.
            if "*" not in allowed_domains:
                if not _domain_allowed(host, allowed_domains):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Domain not allowed for this API key. Origin={origin}",
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

    # Add more rules here as you like...
    return list(dict.fromkeys(recommendations))  # unique, keep order

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
def usage(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    # This counts as a request too (so it increments usage).
    # If you don't want that, I’ll show you how to skip incrementing for /usage.
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)
