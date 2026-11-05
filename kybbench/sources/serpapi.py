"""Google results via SerpAPI: result links only, used the same way as kybbench.sources.brave.

Live titles and snippets are not used (they describe the page as it is today); case text comes
from Wayback captures made on or before the case date.

Key: https://serpapi.com -> SERPAPI_API_KEY. The free plan allows 250 searches a month.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

import requests

URL = "https://serpapi.com/search.json"
ACCOUNT = "https://serpapi.com/account.json"
CACHE_DIR = Path("data/cache/serpapi")
# Hard monthly cap, kept below the plan's 15,000 so reruns and checks have headroom
BUDGET = int(os.environ.get("KYB_SERPAPI_BUDGET", "14000"))
CHECK_EVERY = 25  # confirm usage with SerpAPI's account endpoint (free) every N new searches
_since_check, _usage = CHECK_EVERY, None
_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def usage():
    r = requests.get(ACCOUNT, params={"api_key": os.environ["SERPAPI_API_KEY"]}, timeout=30)
    r.raise_for_status()
    return r.json()["this_month_usage"]


def _spend():
    """Refuse a new (uncached) search once this month's usage reaches BUDGET."""
    global _since_check, _usage
    with _lock:
        if _since_check >= CHECK_EVERY or _usage is None:
            _usage, _since_check = usage(), 0
        if _usage >= BUDGET:
            raise BudgetExceeded(f"SerpAPI usage {_usage} has reached the cap of {BUDGET} this month")
        _usage += 1
        _since_check += 1


def search(query, count=10):
    key = re.sub(r"[^A-Za-z0-9]+", "_", query)[:180]
    cached = CACHE_DIR / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    _spend()
    params = {"engine": "google", "q": query, "gl": "uk", "hl": "en", "google_domain": "google.co.uk",
              "num": count, "api_key": os.environ["SERPAPI_API_KEY"]}
    for attempt in range(8):  # transient 5xx runs can last minutes; cached queries are never re-billed
        try:
            r = requests.get(URL, params=params, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            urls = [res["link"] for res in r.json().get("organic_results", []) if res.get("link")]
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(urls))
            return urls
        if r.status_code not in (429, 500, 502, 503):
            raise RuntimeError(f"SerpAPI {r.status_code}: {r.text[:200]}")
        time.sleep(min(120, 2 ** (attempt + 2)))
    raise RuntimeError(f"SerpAPI: gave up on {query!r}")
