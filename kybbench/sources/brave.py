"""Brave Search API: result links for a company, used as the search source for case files.

Only the links are used. Titles and snippets from the live results describe the page as it is
today and can leak the outcome; the case text comes from Wayback captures made on or before the
case date (kybbench.sources.wayback).

Key: https://brave.com/search/api/ -> BRAVE_API_KEY.
"""

import json
import os
import re
import time
from pathlib import Path

import requests

URL = "https://api.search.brave.com/res/v1/web/search"
CACHE_DIR = Path("data/cache/brave")
MIN_INTERVAL = 1.1  # the free plan allows about one query a second
_last = 0.0


def search(query, until=None, count=10):
    """Result URLs for query. `until` restricts to pages Brave dates on or before it; avoid it for
    case files: Brave drops every page it cannot date, and the Wayback rule already enforces dates."""
    global _last
    key = re.sub(r"[^A-Za-z0-9]+", "_", f"{query}_{until}")[:180]
    cached = CACHE_DIR / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    params = {"q": query, "count": count, "country": "gb", "search_lang": "en", "safesearch": "off"}
    if until:
        params["freshness"] = f"1990-01-01to{until}"
    headers = {"Accept": "application/json", "X-Subscription-Token": os.environ["BRAVE_API_KEY"]}
    for attempt in range(6):
        wait = _last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        try:
            r = requests.get(URL, params=params, headers=headers, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            urls = [res["url"] for res in (r.json().get("web") or {}).get("results", [])]
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(urls))
            return urls
        if r.status_code not in (429, 500, 502, 503):
            raise RuntimeError(f"Brave {r.status_code}: {r.text[:200]}")
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"Brave: gave up on {query!r}")
