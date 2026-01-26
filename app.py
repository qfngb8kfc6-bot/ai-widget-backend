from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any, List, Tuple
from collections import defaultdict
from urllib.parse import urlparse, urljoin

import re
import httpx
from bs4 import BeautifulSoup

app = FastAPI(title="AI Widget Backend (Scrape + Rank + Explain)")

# --------------------------------------------------
# CORS (allow widget + GitHub Pages)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock later per domain if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING + OPTIONAL BRANDING
# --------------------------------------------------
API_KEYS = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
        "usage": 0,
        "branding": {
            "name": "Acme",
            "primaryColor": "#0b1020",
            "secondaryColor": "#2aaabe",
            "logoUrl": ""  # optional
        }
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
        "usage": 0,
        "branding": {
            "name": "Demo",
            "primaryColor": "#0b1020",
            "secondaryColor": "#2aaabe",
            "logoUrl": ""
        }
    }
}

USAGE_COUNTER = defaultdict(int)

# --------------------------------------------------
# REQUEST MODEL (matches your new widget fields)
# --------------------------------------------------
class RequestData(BaseModel):
    website_url: HttpUrl
    industry: str
    goal: str

# --------------------------------------------------
# AUTH + DOMAIN CHECK
# --------------------------------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> Tuple[str, Dict[str, Any]]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format (use Bearer ...)")

    key = authorization.replace("Bearer ", "").strip()

    for client, data in API_KEYS.items():
        if key == data["key"]:
            origin = request.headers.get("origin", "") or ""
            allowed = data.get("domains", [])

            if "*" not in allowed:
                if origin:
                    if not any(d in origin for d in allowed):
                        raise HTTPException(status_code=403, detail="Domain not allowed for this API key")
                # If origin missing (some contexts), you can choose to allow or deny.
                # We'll allow if origin missing to avoid breaking server-to-server tests.

            USAGE_COUNTER[client] += 1
            return client, data

    raise HTTPException(status_code=403, detail="Invalid API key")

# --------------------------------------------------
# SCRAPING HELPERS (very lightweight crawler)
# --------------------------------------------------
UA = "AIWidgetBot/1.0 (+https://example.com)"

def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s

def extract_page_text(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    # remove junk
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = clean_text(soup.title.get_text()) if soup.title else ""
    desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = clean_text(meta["content"])

    headings = []
    for h in soup.find_all(["h1", "h2"]):
        t = clean_text(h.get_text())
        if t:
            headings.append(t)

    body_text = clean_text(soup.get_text(" "))
    # keep it capped (we only need a summary signal)
    body_text = body_text[:20000]

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = clean_text(a.get_text())[:80]
        links.append({"href": href, "text": text})

    return {
        "title": title,
        "description": desc,
        "headings": headings[:25],
        "text": body_text,
        "links": links[:400],
    }

async def fetch_url(url: str, timeout_s: float = 8.0) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": UA}
        ) as client:
            r = await client.get(url)
            if r.status_code >= 400:
                return {"ok": False, "url": url, "status": r.status_code, "error": f"HTTP {r.status_code}"}
            data = extract_page_text(r.text)
            return {"ok": True, "url": str(r.url), "status": r.status_code, "page": data}
    except Exception as e:
        return {"ok": False, "url": url, "status": 0, "error": str(e)}

def same_site(a: str, b: str) -> bool:
    try:
        pa, pb = urlparse(a), urlparse(b)
        return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)
    except:
        return False

def pick_candidate_links(base_url: str, links: List[Dict[str, str]]) -> List[str]:
    """
    Try to find likely "services/solutions/what-we-do" pages.
    """
    keywords = ["service", "services", "solutions", "what-we-do", "whatwedo", "offer", "capabilities"]
    candidates = []

    for l in links:
        href = l.get("href", "")
        if not href:
            continue
        full = urljoin(base_url, href)
        if not same_site(base_url, full):
            continue
        low = full.lower()
        if any(k in low for k in keywords):
            candidates.append(full)

    # de-dup, keep small
    out = []
    for u in candidates:
        if u not in out:
            out.append(u)
    return out[:2]  # only 2 extra pages (keeps it fast + safe)

async def crawl_site(seed_url: str) -> Dict[str, Any]:
    """
    Fetch seed page + up to 2 service-like pages.
    """
    fetched = []
    seed = await fetch_url(seed_url)
    fetched.append(seed)

    if seed.get("ok") and seed.get("page"):
        extra = pick_candidate_links(seed["url"], seed["page"]["links"])
        for u in extra:
            fetched.append(await fetch_url(u))

    ok_pages = [f for f in fetched if f.get("ok")]
    combined_text = " ".join([p["page"]["title"] + " " + p["page"]["description"] + " " + " ".join(p["page"]["headings"]) + " " + p["page"]["text"] for p in ok_pages])
    combined_text = combined_text[:40000]

    return {
        "pages_fetched": [{"url": f.get("url"), "ok": f.get("ok"), "status": f.get("status"), "error": f.get("error", "")} for f in fetched],
        "combined_text": combined_text,
    }

# --------------------------------------------------
# INFERENCE: what services the company already offers (rough heuristic)
# --------------------------------------------------
OFFER_KEYWORDS = {
    "SEO": ["seo", "search engine optimization", "rank on google"],
    "Paid Ads": ["google ads", "ppc", "paid ads", "meta ads", "facebook ads"],
    "Web Design": ["web design", "website design", "ui design"],
    "Web Development": ["web development", "developer", "custom website", "wordpress", "shopify"],
    "Copywriting": ["copywriting", "website copy", "content writing"],
    "Branding": ["branding", "brand identity", "logo design"],
    "Email Marketing": ["email marketing", "newsletter", "klaviyo", "mailchimp"],
    "Social Media": ["social media", "instagram", "tiktok", "content calendar"],
    "Lead Gen": ["lead generation", "funnels", "conversion rate", "cro"],
    "Analytics": ["analytics", "tracking", "ga4", "google analytics"],
}

def infer_offered_services(text: str) -> List[str]:
    low = (text or "").lower()
    offered = []
    for name, kws in OFFER_KEYWORDS.items():
        if any(k in low for k in kws):
            offered.append(name)
    return offered

# --------------------------------------------------
# RECOMMENDER: ranked services with % + reasons
# --------------------------------------------------
SERVICE_CATALOG = [
    {
        "service": "Website copywriting",
        "keywords": ["copy", "messaging", "value proposition", "landing page copy", "conversion"],
        "best_for_goals": ["leads", "lead generation", "more leads", "sales", "conversions"],
    },
    {
        "service": "Landing page creation",
        "keywords": ["landing page", "offer", "cta", "conversion", "signup"],
        "best_for_goals": ["leads", "lead generation", "more leads", "sales", "conversions"],
    },
    {
        "service": "SEO optimization",
        "keywords": ["seo", "organic", "search", "keywords", "rank"],
        "best_for_goals": ["traffic", "visibility", "growth", "leads", "lead generation"],
    },
    {
        "service": "Lead funnel optimization",
        "keywords": ["funnel", "conversion", "cro", "forms", "booking", "lead"],
        "best_for_goals": ["le]()
