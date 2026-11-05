"""Domain registration dates from RDAP (the registries' public lookup service). Free, no key.

The date returned is the current registration's creation date. If a domain lapsed and was
re-registered, this is the newer date, so a creation date after the case date means the site
found today is not the one that existed then.
"""

import json
import re
import time
from pathlib import Path

import requests

HEADERS = {"User-Agent": "kybbench/0.1 (+https://kyb-bench.vercel.app)", "Accept": "application/rdap+json"}
CACHE_DIR = Path("data/cache/rdap")


def registered(domain):
    """Creation date (YYYY-MM-DD) of the domain's current registration, or None."""
    domain = domain.lower().removeprefix("www.")
    cached = CACHE_DIR / f"{re.sub(r'[^a-z0-9.]+', '_', domain)}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    url = (f"https://rdap.nominet.uk/uk/domain/{domain}" if domain.endswith(".uk")
           else f"https://rdap.org/domain/{domain}")
    date = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            for e in r.json().get("events", []):
                if e.get("eventAction") == "registration":
                    date = e.get("eventDate", "")[:10] or None
            break
        if r.status_code == 404:
            break
        time.sleep(2 ** attempt)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(date))
    return date
