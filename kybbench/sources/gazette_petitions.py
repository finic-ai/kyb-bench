"""Channel `public_interest_wound_up`: companies the Secretary of State petitioned to wind up in the
public interest, from The Gazette's "Petitions to Wind Up (Companies)" notices.

Most of these never get an Insolvency Service press release. A petition does not say why, so the
channel is broader than fake or front companies: it is any company the government moved to shut
down for misconduct. The petition's publication date is its exposure date.
"""

import re
import time

import requests

SEARCH = "https://www.thegazette.co.uk/all-notices/notice/data.json"
HEADERS = {"Accept": "application/json", "User-Agent": "kybbench/0.1 (+https://kyb-bench.vercel.app)"}
PETITIONS = "G205010000"
NUMBER = re.compile(r"Company\s+(?:Number|No\.?)\s*:?\s*((?:SC|NI|OC|SO|NC)?\d{6,8})", re.I)
NAME = re.compile(r"In the Matter of\s+(.{3,120}?)\s+\(Company Number", re.I)
NOTICE = "https://www.thegazette.co.uk/notice/{}"


def _get(params, tries=5):
    for attempt in range(tries):
        try:
            r = requests.get(SEARCH, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt + 1)
    raise RuntimeError(f"Gazette: gave up on {params}")


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def notice_details(notice_id):
    """Company name and number from the notice page (search results carry only an excerpt)."""
    for attempt in range(5):
        try:
            r = requests.get(NOTICE.format(notice_id), headers={**HEADERS, "Accept": "text/html"}, timeout=60)
            if r.status_code == 200:
                text = _text(r.text)
                num, name = NUMBER.search(text), NAME.search(text)
                return (name.group(1).strip() if name else None, num.group(1).upper() if num else None)
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt + 1)
    return None, None


def petitions(since):
    """Public-interest winding-up petitions published on or after `since`, one row per notice."""
    rows, page = [], 1
    while True:
        body = _get({"text": '"public interest"', "categorycode": PETITIONS, "start-publish-date": since,
                     "results-page-size": 100, "results-page": page})
        entries = body.get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            name, number = notice_details(e.get("id", "").rstrip("/").split("/")[-1])
            rows.append({"date": e.get("published", "")[:10], "url": e.get("id"), "company_number": number,
                         "name": name})
            time.sleep(0.5)
        if page * 100 >= int(body.get("f:total", 0)) or not entries:
            return rows
        page += 1
        time.sleep(1)
