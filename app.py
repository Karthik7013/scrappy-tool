# app.py
import os
import re
import ipaddress
import socket
from urllib.parse import urlparse
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import requests
from bs4 import BeautifulSoup
import time

app = FastAPI(title="Scraping Playground")

def is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False

def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.hostname:
            return False
        hostname = parsed.hostname.lower()
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        ip = socket.gethostbyname(hostname)
        if is_private_ip(ip):
            return False
        return True
    except Exception:
        return False

# ✅ CORRECT TEMPLATES PATH
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/check-url")
async def check_url(request: Request):
    data = await request.json()
    url = data.get("url", "").strip()

    if not url:
        return {"allowed": False, "message": "URL is empty"}

    if not is_allowed_url(url):
        return {
            "allowed": False,
            "message": "❌ Not allowed: private IP, localhost, or invalid scheme"
        }

    # Basic robots.txt check
    try:
        robots_url = f"{url.rstrip('/')}/robots.txt"
        robots_resp = requests.get(robots_url, timeout=5)
        if robots_resp.status_code == 200:
            content = robots_resp.text
            if "User-agent: *" in content and "Disallow: /" in content:
                return {
                    "allowed": False,
                    "message": "❌ Blocked by robots.txt (disallows all bots)"
                }
    except:
        pass  # Ignore errors (e.g., no robots.txt)

    return {
        "allowed": True,
        "message": "✅ Allowed to scrape (be respectful!)"
    }

@app.post("/scrape")
async def scrape(request: Request):
    data = await request.json()
    url = data.get("url", "").strip()
    selector = data.get("selector", "").strip()

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    if not is_allowed_url(url):
        raise HTTPException(status_code=400, detail="URL not allowed (private/local)")

    # Rate limiting: 2 seconds per IP
    client_ip = request.client.host
    now = time.time()
    last_time = getattr(app, "_last_request", {})
    if client_ip in last_time and now - last_time[client_ip] < 2:
        raise HTTPException(status_code=429, detail="Rate limit: wait 2 seconds between requests")
    app._last_request = {client_ip: now}

    try:
        headers = {
            "User-Agent": "ScrapingPlayground/1.0 (+https://scrappy-tool.onrender.com)"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=408, detail="Timeout fetching page")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Fetch error: {str(e)}")

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    if selector:
        try:
            elements = soup.select(selector)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid CSS selector: {str(e)}")
        
        for i, el in enumerate(elements[:50]):
            text = el.get_text(strip=True)
            if text:
                results.append({
                    "field": f"Item {i+1}",
                    "value": text
                })
    else:
        for i, tag in enumerate(soup.find_all(["p", "h1", "h2", "h3", "h4", "span", "div", "li"])[:20]):
            text = tag.get_text(strip=True)
            if text and len(text) > 10:
                results.append({
                    "field": f"Text {i+1}",
                    "value": text
                })

    html_preview = str(soup)[:500] + "..."

    return {
        "data": results,
        "html_preview": html_preview,
        "count": len(results)
    }