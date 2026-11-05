"""Companies House API client, with a disk cache, and the rebuild of a company as of a date.

Historical bulk snapshots are not archived, so `snapshot(number, as_of)` rebuilds the registry
section of a case from today's records and their dates: officers and PSCs active on the date,
filings up to the date, and status on the date. Fields that cannot be rebuilt reliably are
returned as null and listed in `_unknown`, never guessed.

API key: https://developer.company-information.service.gov.uk/ -> set COMPANIES_HOUSE_API_KEY.
"""

import json
import re
import os
import time
from pathlib import Path

import requests

BASE = "https://api.company-information.service.gov.uk"
CACHE_DIR = Path("data/cache/companies_house")
# 600 requests per 5 minutes; stay a little under
MIN_INTERVAL = 300 / 560

_last = 0.0
_session = requests.Session()


def _get(path, params=None, cache_dir=CACHE_DIR):
    global _last
    key = path.strip("/").replace("/", "__") + ("__" + "_".join(f"{k}-{v}" for k, v in sorted(params.items())) if params else "")
    cached = Path(cache_dir) / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not api_key:
        raise RuntimeError(f"{path} not cached and COMPANIES_HOUSE_API_KEY is not set")
    for attempt in range(6):
        wait = _last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        try:
            r = _session.get(BASE + path, params=params, auth=(api_key, ""), timeout=30)
        except requests.RequestException:
            time.sleep(min(60, 2 ** attempt))
            continue
        if r.status_code == 404:
            body = None
            break
        if r.status_code == 200:
            body = r.json()
            break
        if r.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"Companies House {r.status_code} on {path}: {r.text[:200]}")
        time.sleep(min(60, 2 ** attempt))
    else:
        raise RuntimeError(f"Companies House: gave up on {path}")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(body))
    return body


def _all_items(path, page=100):
    items, start = [], 0
    while True:
        body = _get(path, {"items_per_page": page, "start_index": start})
        if not body:
            return items
        batch = body.get("items", [])
        items += batch
        start += len(batch)
        if not batch or start >= body.get("total_results", body.get("total_count", 0)):
            return items


def company(number):
    return _get(f"/company/{number}")


def officers(number):
    return _all_items(f"/company/{number}/officers")


def pscs(number):
    return _all_items(f"/company/{number}/persons-with-significant-control")


def filings(number):
    return _all_items(f"/company/{number}/filing-history")


def officer_appointments(officer_link):
    return _all_items(officer_link)


def search_officers(name):
    body = _get("/search/officers", {"q": name, "items_per_page": 50})
    return body.get("items", []) if body else []


def search_disqualified(name):
    body = _get("/search/disqualified-officers", {"q": name})
    return body.get("items", []) if body else []


_COUNTRY = re.compile(r"(\s+(england|wales|scotland|northern ireland|united kingdom|uk|gb))+$", re.I)


def canonical_address(addr):
    """One plain line with no commas or country, whichever source the address came from: profile
    addresses arrive as comma-separated parts with a country, filing-history addresses as bare
    strings, and the difference would reveal how the address was rebuilt."""
    if not addr:
        return None
    line = " ".join(addr.replace(",", " ").split())
    return _COUNTRY.sub("", line) or None


def _one_line(addr):
    if not addr:
        return None
    if isinstance(addr, str):
        return canonical_address(addr)
    keys = ("premises", "address_line_1", "address_line_2", "locality", "region", "postal_code")
    return canonical_address(" ".join(str(addr[k]).strip() for k in keys if addr.get(k)))


def _on_or_before(date, as_of):
    return date is not None and date <= as_of


def _active(start, end, as_of):
    return _on_or_before(start, as_of) and (end is None or end > as_of)


def snapshot(number, as_of):
    """The `registry` section of a case for a UK company as of `as_of` (YYYY-MM-DD)."""
    profile = company(number)
    if profile is None:
        raise ValueError(f"company {number} not found")
    if profile.get("date_of_creation", "9999") > as_of:
        raise ValueError(f"company {number} was incorporated after {as_of}")
    unknown = []

    history = [f for f in filings(number) if _on_or_before(f.get("date"), as_of)]
    ceased = profile.get("date_of_cessation")
    if ceased and ceased <= as_of:
        # The status field can say "active" for a company dissolved without restoration; trust the
        # cessation date unless a restoration was filed between it and as_of.
        restored = any(f.get("category") == "restoration" and ceased <= f.get("date", "") <= as_of for f in history)
        current = profile.get("company_status")
        status = "active" if restored else (current if current and current != "active" else "dissolved")
    else:
        status = "active"
        if any(f.get("category") in ("insolvency", "liquidation") for f in history):
            status, unknown = None, unknown + ["status"]

    # The office at as_of is today's office unless it changed since. If it did: the latest change on
    # or before as_of records the address then in force (new_address); failing that, the first
    # change after as_of records it as old_address. A registrar default (RP05) records neither.
    # Every address is rendered as one line, so its format cannot reveal how it was rebuilt.
    moves = sorted((f for f in filings(number) if f.get("category") == "address"), key=lambda f: f.get("date", ""))
    after = [f for f in moves if f.get("date", "") > as_of]
    before = [f for f in moves if f.get("date", "") <= as_of and (f.get("description_values") or {}).get("new_address")]
    if not after:
        address = _one_line(profile.get("registered_office_address"))
    elif before:
        address = _one_line(before[-1]["description_values"]["new_address"])
    else:
        address = _one_line((after[0].get("description_values") or {}).get("old_address"))
    if not address:
        unknown.append("registered_address")

    officer_rows = []
    for o in officers(number):
        if not _active(o.get("appointed_on"), o.get("resigned_on"), as_of):
            continue
        officer_rows.append({
            "name": o.get("name"),
            "role": o.get("officer_role"),
            "appointed": o.get("appointed_on"),
            "nationality": o.get("nationality"),
            "country_of_residence": o.get("country_of_residence"),
            "dob_month": f"{o['date_of_birth']['year']}-{o['date_of_birth']['month']:02d}" if o.get("date_of_birth") else None,
            "appointments_link": o.get("links", {}).get("officer", {}).get("appointments"),
        })

    psc_rows = [
        {"name": p.get("name"), "kind": p.get("kind"), "nature_of_control": p.get("natures_of_control", []),
         "notified": p.get("notified_on"), "country_of_residence": p.get("country_of_residence")}
        for p in pscs(number)
        if _active(p.get("notified_on"), p.get("ceased_on"), as_of)
    ]

    return {
        "company_number": number,
        "name": next((p["name"] for p in profile.get("previous_company_names", [])
                      if p.get("effective_from", "") <= as_of < p.get("ceased_on", "")), profile.get("company_name")),
        "status": status,
        "incorporated": profile.get("date_of_creation"),
        "type": profile.get("type"),
        "sic_codes": profile.get("sic_codes", []),
        "registered_address": address,
        "address_company_count": None,  # filled from the bulk Free Company Data Product
        "officers": officer_rows,
        "psc": psc_rows,
        "filings": [{"date": f.get("date"), "type": f.get("type"), "category": f.get("category"),
                     "description": f.get("description")} for f in history],
        "accounts_category": None,
        "_unknown": unknown,
    }
