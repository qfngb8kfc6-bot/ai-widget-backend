from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from collections import defaultdict
from urllib.parse import urlparse, urljoin
import re
import time

import requests
from bs4 import BeautifulSoup


app = FastAPI(title="AI Widget Backend (Website Scan + Ranked Recommendations)")

# --------------------------------------------------
# CORS
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock later per domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# API KEYS + DOMAIN LOCKING + USAGE
# --------------------------------------------------
API_KEYS = {
    "acme": {
        "key": "cust_live_acme_9xK2",
        "domains": ["acme.com"],
    },
    "demo": {
        "key": "cust_demo_123",
        "domains": ["localhost", "github.io"],
    },
}

USAGE_COUNTER = defaultdict(int)

# Small in-memory cache so you don’t fetch the same site constantly
FETCH_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 60 * 10  # 10 minutes


# --------------------------------------------------
# DATA MODEL (WIDGET INPUT)
# --------------------------------------------------
class RecommendRequest(BaseModel):
    website_url: str
    industry: str
    goal: str


# --------------------------------------------------
# HELPERS: AUTH + DOMAIN LOCK
# --------------------------------------------------
def verify_api_key(authorization: Optional[str], request: Request) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth format")

    key = authorization.replace("Bearer ", "").strip()

    origin = request.headers.get("origin", "")  # e.g. https://client.com
    for client, data in API_KEYS.items():
        if key == data["key"]:
            allowed_domains = data["domains"]
            if "*" not in allowed_domains:
                if not any(domain in origin for domain in allowed_domains):
                    raise HTTPException(status_code=403, detail="Domain not allowed for this API key")

            USAGE_COUNTER[client] += 1
            return client

    raise HTTPException(status_code=403, detail="Invalid API key")


# --------------------------------------------------
# HELPERS: URL + FETCH + TEXT EXTRACTION
# --------------------------------------------------
def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url

def domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def safe_fetch(url: str, timeout: int = 8) -> str:
    """
    Fetch HTML safely with caching. Many sites block bots; we keep it minimal.
    """
    now = time.time()
    cached = FETCH_CACHE.get(url)
    if cached and now - cached["ts"] < CACHE_TTL_SECONDS:
        return cached["html"]

    headers = {
        "User-Agent": "AIWidgetBot/1.0 (+https://example.com)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        html = resp.text if resp.status_code == 200 else ""
    except Exception:
        html = ""

    FETCH_CACHE[url] = {"ts": now, "html": html}
    return html

def extract_visible_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # remove junk
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:30000]  # cap size

def find_services_page_links(base_url: str, html: str) -> List[str]:
    """
    Try to find likely "services" pages from the homepage nav links.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ") or "").lower()
        href = a["href"].strip()
        if any(k in label for k in ["services", "what we do", "solutions", "offer", "capabilities"]):
            full = urljoin(base_url, href)
            links.append(full)

        # also if url itself contains these
        if any(k in href.lower() for k in ["/services", "/solutions", "/what-we-do", "/capabilities"]):
            full = urljoin(base_url, href)
            links.append(full)

    # de-dupe, keep only same-domain
    base_domain = domain_from_url(base_url)
    uniq = []
    for u in links:
        if domain_from_url(u) == base_domain and u not in uniq:
            uniq.append(u)

    return uniq[:3]  # keep it light

def extract_offered_services_from_text(text: str) -> List[str]:
    """
    Very simple extraction: look for common service phrases mentioned on the page.
    """
    if not text:
        return []

    # Expand this list over time
    service_phrases = [
        "web design", "website design", "seo", "search engine optimization", "ppc",
        "google ads", "facebook ads", "content marketing", "copywriting",
        "branding", "logo design", "social media management", "email marketing",
        "lead generation", "conversion rate optimization", "cro",
        "video production", "graphic design", "ui/ux", "analytics", "strategy",
        "wordpress", "shopify", "ecommerce", "app development", "software development"
    ]

    found = []
    lower = text.lower()
    for p in service_phrases:
        if p in lower:
            found.append(p)

    # normalize display names
    cleaned = sorted(list(set([title_case_service(s) for s in found])))
    return cleaned[:20]

def title_case_service(s: str) -> str:
    # keep SEO/UX etc readable
    s2 = s.strip().title()
    s2 = s2.replace("Seo", "SEO").replace("Ppc", "PPC").replace("Cro", "CRO").replace("Ui/Ux", "UI/UX")
    return s2


# --------------------------------------------------
# RECOMMENDATION ENGINE (keyword scoring -> % + why)
# --------------------------------------------------
SERVICE_CATALOG = {
    "SEO optimization": {
        "keywords": ["seo", "search engine", "organic traffic", "rank", "google"],
        "goal_boost": ["traffic", "visibility", "leads"],
    },
    "Landing page creation": {
        "keywords": ["landing page", "conversion", "campaign", "signup", "form"],
        "goal_boost": ["leads", "lead generation", "signups", "convert"],
    },
    "Website copywriting": {
        "keywords": ["copywriting", "messaging", "positioning", "tone of voice", "headline"],
        "goal_boost": ["sales", "leads", "convert"],
    },
    "Paid ads (Google/Facebook)": {
        "keywords": ["ppc", "google ads", "facebook ads", "paid ads", "ad campaign"],
        "goal_boost": ["leads", "sales", "growth"],
    },
    "Email marketing automation": {
        "keywords": ["email", "newsletter", "automation", "crm", "sequence"],
        "goal_boost": ["leads", "retention", "sales"],
    },
    "Analytics & conversion tracking": {
        "keywords": ["analytics", "tracking", "ga4", "pixels", "events", "conversion tracking"],
        "goal_boost": ["leads", "roi", "growth"],
    },
    "Branding & positioning": {
        "keywords": ["brand", "branding", "positioning", "identity", "story"],
        "goal_boost": ["awareness", "trust", "premium"],
    },
    "Content strategy": {
        "keywords": ["content", "blog", "articles", "content strategy", "thought leadership"],
        "goal_boost": ["traffic", "visibility", "trust"],
    },
}

def score_service(service_name: str, site_text: str, industry: str, goal: str) -> Dict[str, Any]:
    meta = SERVICE_CATALOG[service_name]
    keywords = meta["keywords"]
    goal_boost = meta["goal_boost"]

    t = (site_text or "").lower()
    ind = (industry or "").lower()
    g = (goal or "").lower()

    # base score
    score = 10

    matched = []
    for kw in keywords:
        if kw in t:
            score += 18
            matched.append(kw)

    # industry + goal boosts
    if "marketing" in ind and service_name in ["SEO optimization", "Landing page creation", "Paid ads (Google/Facebook)"]:
        score += 12

    for gb in goal_boost:
        if gb in g:
            score += 15

    # clamp
    score = max(0, min(score, 100))

    why_parts = []
    if matched:
        why_parts.append(f"Detected signals on the website: {', '.join(matched[:4])}.")
    if any(gb in g for gb in goal_boost):
        why_parts.append(f"Matches your goal (“{goal}”).")
    if "marketing" in ind:
        why_parts.append(f"Commonly high-impact for {industry}.")

    if not why_parts:
        why_parts.append("Recommended based on your industry + goal signals.")

    return {"name": service_name, "score": score, "why": " ".join(why_parts)}


def normalize_scores(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert raw scores into ranked percentages (sum ~= 100).
    """
    if not items:
        return []
    total = sum(i["score"] for i in items) or 1
    for i in items:
        i["percent"] = round((i["score"] / total) * 100)
    # Adjust rounding to exactly 100
    diff = 100 - sum(i["percent"] for i in items)
    if diff != 0:
        items[0]["percent"] += diff
    return items


# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/recommend")
def recommend(data: RecommendRequest, request: Request, authorization: Optional[str] = Header(None)):
    client = verify_api_key(authorization, request)

    # 1) Scan the website_url the user typed
    website_url = normalize_url(data.website_url)
    home_html = safe_fetch(website_url)
    site_text = extract_visible_text(home_html)

    # Try a couple “services” links (still lightweight)
    service_links = find_services_page_links(website_url, home_html)
    for link in service_links:
        extra_html = safe_fetch(link)
        site_text += " " + extract_visible_text(extra_html)

    site_text = site_text[:60000]

    # 2) Scan the site where the widget is embedded (Origin header)
    origin = request.headers.get("origin", "")
    origin_text = ""
    origin_services = []
    if origin:
        origin_home = origin.rstrip("/")  # e.g. https://client.com
        origin_html = safe_fetch(origin_home)
        origin_text = extract_visible_text(origin_html)

        origin_links = find_services_page_links(origin_home, origin_html)
        for link in origin_links:
            origin_text += " " + extract_visible_text(safe_fetch(link))

        origin_services = extract_offered_services_from_text(origin_text)

    # 3) Score + rank
    scored = []
    for service_name in SERVICE_CATALOG.keys():
        scored.append(score_service(service_name, site_text, data.industry, data.goal))

    # take top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:5]
    top = normalize_scores(top)

    return {
        "client": client,
        "input": {
            "website_url": data.website_url,
            "industry": data.industry,
            "goal": data.goal,
        },
        "detected": {
            "typed_site_domain": domain_from_url(website_url),
            "embed_origin": origin,
            "company_offers_on_embed_site": origin_services,  # what their site seems to already offer
        },
        "recommended": top,  # [{name, score, percent, why}]
    }

@app.get("/usage")
def usage(request: Request, authorization: Optional[str] = Header(None)):
    # Protect usage endpoint as well
    verify_api_key(authorization, request)
    return dict(USAGE_COUNTER)
