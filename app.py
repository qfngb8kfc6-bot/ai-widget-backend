from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
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
# API KEYS + DOMAIN LOCKING
# --------------------------------------------------

API_KEYS = {
    "demo": {
        "key": "demo-key-123",
        "domains": ["*"],  # allow all for demo
    },
    # Example real client:
    # "client1": {
    #     "key": "client1-secret-key",
    #     "domains": ["example.com", "www.example.com"]
    # }
}

# Usage tracking (in-memory for now)
USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# DATA MODEL
# --------------------------------------------------

class RequestData(BaseModel):
    company_name: Optional[str] = ""
    industry: str
    company_size: str
    goal: str

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def verify_api_key(authorization: Optional[str], request: Request):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "")

    for client, data in API_KEYS.items():
        if key == data["key"]:
            # Domain check
            origin = request.headers.get("origin", "")
            allowed_domains = data["domains"]

            if "*" not in allowed_domains:
                if not any(domain in origin for domain in allowed_domains):
                    raise HTTPException(
                        status_code=403,
                        detail="Domain not allowed for this API key",
                    )

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")

def recommend_services(industry: str, company_size: str, goal: str):
    recommendations = []

    if "marketing" in industry.lower():
        recommendations.extend([
            "Website copywriting",
            "Landing page creation",
            "SEO optimization"
        ])

    if goal.lower() in ["lead generation", "leads"]:
        recommendations.append("Lead funnel optimization")

    if company_size.lower() in ["small", "startup"]:
        recommendations.append("Affordable growth strategy")

    return list(set(recommendations))

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

    services = recommend_services(
        data.industry,
        data.company_size,
        data.goal
    )

    return {
        "client": client,
        "recommended_services": services
    }

@app.get("/usage")
def usage(authorization: Optional[str] = Header(None)):
    verify_api_key(authorization, Request)
    return dict(USAGE_COUNTER)
