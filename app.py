from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import urlparse
import os
import sqlite3
from datetime import date

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # allow browser calls
    allow_credentials=False,      # keep False with wildcard origins
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origins=[
        "https://qfngb8kfc6-bot.github.io",
        # later add: "https://yourdomain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEYS = {
    "demo": "Demo Customer",
    "cust_live_123": "Customer A",
}

class RequestData(BaseModel):
    company_name: str | None = ""
    industry: str
    company_size: str
    goal: str

def verify_api_key(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization format")

    key = parts[1]
    if key not in API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return key  # or return customer name

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/recommend")
def recommend(data: RequestData, authorization: str | None = Header(default=None)):
    customer_key = verify_api_key(authorization)

    # Your existing logic here:
    # services = recommend_services(data.industry, data.company_size, data.goal)
    services = ["Website copywriting", "Landing page creation", "SEO optimization"]

    return {"recommended_services": services, "customer": customer_key}

CUSTOMERS = {
    # API_KEY: customer config
    "demo": {
        "name": "Demo",
        "allowed_domains": ["qfngb8kfc6-bot.github.io"],  # no https:// here, just domain
        "active": True,
    },
    "cust_live_123": {
        "name": "Customer A",
        "allowed_domains": ["customer.com", "www.customer.com"],
        "active": True,
    },
}
DB_PATH = os.getenv("USAGE_DB_PATH", "usage.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL,
            api_key TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY(day, api_key)
        )
    """)
    conn.commit()
    conn.close()

init_db()

def track_usage(api_key: str):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO usage(day, api_key, count)
        VALUES (?, ?, 1)
        ON CONFLICT(day, api_key)
        DO UPDATE SET count = count + 1
    """, (today, api_key))
    conn.commit()
    conn.close()

