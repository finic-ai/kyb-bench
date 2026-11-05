"""Channel `registrar_action`: companies whose registered office the registrar moved to the
Companies House default address (filing type RP05) because it was not an appropriate address.

The default address has postcode CF14 8LH. Advanced search lists companies currently there;
each company's filing history gives the date the default address was applied.
"""

from kybbench import companies_house as ch

import datetime as dt

DEFAULT_POSTCODE = "CF14 8LH"
PAGE = 5000
MAX_RESULTS = 10000  # advanced search returns 500 past this offset


def _search(params, start=0):
    return ch._get("/advanced-search/companies", {**params, "size": PAGE, "start_index": start}) or {}


def _window(status, lo, hi):
    """All matches incorporated in [lo, hi], splitting the range while it has too many hits."""
    params = {"location": DEFAULT_POSTCODE, "company_status": status,
              "incorporated_from": lo.isoformat(), "incorporated_to": hi.isoformat()}
    first = _search(params)
    hits = first.get("hits", 0)
    if hits > MAX_RESULTS and hi > lo:
        mid = lo + (hi - lo) // 2
        return _window(status, lo, mid) + _window(status, mid + dt.timedelta(days=1), hi)
    out, start = first.get("items", []), len(first.get("items", []))
    while start < min(hits, MAX_RESULTS):
        items = _search(params, start).get("items", [])
        if not items:
            break
        out += items
        start += len(items)
    return out


def companies_at_default_address(status="active"):
    return _window(status, dt.date(1850, 1, 1), dt.date.today())


def default_address_applied(number):
    """Date of the most recent RP05 filing, or None."""
    for f in ch.filings(number):
        if f.get("type") == "RP05":
            return f.get("description_values", {}).get("change_date") or f.get("date")
    return None
