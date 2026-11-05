"""The Gazette: official notices about a company, used for the earliest-public-sign check
(SPEC.md 4.3).

Searching by company number also returns Companies House supplement pages that list thousands
of numbers; those have no notice category and are ignored. Only categorised notices count.
"""

import time

import requests

SEARCH = "https://www.thegazette.co.uk/all-notices/notice/data.json"
# The Gazette rejects the default python-requests user agent
HEADERS = {"Accept": "application/json", "User-Agent": "kybbench/0.1 (+https://kyb-bench.vercel.app)"}
TROUBLE = (
    "petition", "winding-up", "winding up", "provisional liquidator", "liquidator",
    "disqualif", "striking off", "strike off", "administration", "receiver",
)


def notices(company_number, tries=5):
    entries, page = [], 1
    while True:
        for attempt in range(tries):
            try:
                r = requests.get(SEARCH, params={"text": company_number, "results-page-size": 100,
                                                 "results-page": page}, timeout=30, headers=HEADERS)
                if r.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"Gazette: gave up on {company_number}")
        body = r.json()
        batch = body.get("entry") or []
        if isinstance(batch, dict):
            batch = [batch]
        entries += batch
        if page * 100 >= int(body.get("f:total", 0)) or not batch:
            break
        page += 1
    out = []
    for e in entries:
        cat = e.get("category")
        term = cat.get("@term") if isinstance(cat, dict) else None
        if not term:
            continue
        out.append({"date": e.get("published", "")[:10], "category": term, "url": e.get("id"),
                    "trouble": any(t in term.lower() for t in TROUBLE)})
    return sorted(out, key=lambda n: n["date"])


def earliest_trouble(company_number):
    hits = [n for n in notices(company_number) if n["trouble"]]
    return hits[0] if hits else None
