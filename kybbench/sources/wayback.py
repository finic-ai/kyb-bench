"""Wayback Machine lookups, used to freeze web evidence at a case date (SPEC.md 3).

A search result or website enters a case only through a capture made on or before the case's
as_of date; its text comes from that capture, never from the live page or a search snippet.
"""

import html
import json
import re
import time
from pathlib import Path

import requests

CDX = "https://web.archive.org/cdx/search/cdx"
HEADERS = {"User-Agent": "kybbench/0.1 (+https://kyb-bench.vercel.app)"}
CACHE_DIR = Path("data/cache/wayback")


def _get(url, params=None, tries=5, timeout=60):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(min(60, 3 * 2 ** attempt))
    return None


def capture_before(url, as_of):
    """(timestamp, original URL) of the latest successful capture on or before as_of, or None."""
    key = re.sub(r"[^A-Za-z0-9]+", "_", f"{url}_{as_of}")[:180]
    cached = CACHE_DIR / f"cdx_{key}.json"
    if cached.exists():
        return json.loads(cached.read_text()) or None
    r = _get(CDX, {"url": url, "to": as_of.replace("-", ""), "output": "json", "filter": "statuscode:200",
                   "fl": "timestamp,original", "limit": "-1"})
    rows = r.json()[1:] if r is not None and r.text.strip() else []
    out = rows[-1] if rows else None
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(out))
    return out


def page_text(timestamp, original, max_chars=20000):
    """Visible text of an archived page (raw capture, without the Wayback toolbar)."""
    key = re.sub(r"[^A-Za-z0-9]+", "_", f"{timestamp}_{original}")[:180]
    cached = CACHE_DIR / f"page_{key}.txt"
    if cached.exists():
        return cached.read_text()
    r = _get(f"https://web.archive.org/web/{timestamp}id_/{original}")
    text = ""
    if r is not None and "html" in r.headers.get("content-type", ""):
        body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
        title = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.S | re.I)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        if title:
            text = html.unescape(title.group(1).strip()) + " | " + text
    text = text[:max_chars]
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text)
    return text
