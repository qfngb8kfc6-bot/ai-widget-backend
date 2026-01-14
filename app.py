from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rules import recommend_services

API_KEYS = {
    "demo": "sk_demo_123",
    "tamedmedia": "sk_live_tamedmedia_abc123"
}


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://qfngb8kfc6-bot.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

class RequestData(BaseModel):
    company_name: str
    industry: str
    company_size: str
    goal: str

@app.post("/recommend")
def recommend(data: RequestData):
    services = recommend_services(
        data.industry,
        data.company_size,
        data.goal
    )
    return {"recommended_services": services}

from fastapi import Header, HTTPException

def verify_api_key(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Expect: "Bearer sk_xxx"
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = parts[1]

    # Check if key exists in our allowed keys
    if key not in API_KEYS.values():
        raise HTTPException(status_code=403, detail="Invalid API key")

    return True

@app.post("/recommend")
def recommend(data: RequestData, authorization: str | None = Header(default=None)):
    verify_api_key(authorization)

    services = recommend_services(
        data.industry,
        data.company_size,
        data.goal
    )
    return {"recommended_services": services}

import os

API_KEYS = {
    "demo": os.getenv("DEMO_API_KEY"),
    "client1": os.getenv("CLIENT1_API_KEY"),
}

