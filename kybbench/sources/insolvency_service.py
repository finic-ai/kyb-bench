"""Channel `scam_wound_up`: Insolvency Service press releases on GOV.UK.

Only releases about companies wound up (shut down) in the public interest are candidates.
Director bans, Covid loan prosecutions and policy news are kept in the raw file but not used:
pandemic relief fraud is excluded (SPEC.md 4.2) and a director ban alone does not say the
company was fake.
"""

import html
import re
import time

import requests

SEARCH = "https://www.gov.uk/api/search.json"
CONTENT = "https://www.gov.uk/api/content"
WOUND_UP = re.compile(r"shut down|wound up|winding up order", re.I)
COVID = re.compile(r"covid|bounce back|furlough|coronavirus", re.I)
COMPANY_NUMBER = re.compile(r"\b(?:company (?:registration )?(?:number|no\.?)\s*:?\s*)((?:SC|NI|OC|SO|NC)?\d{6,8})\b", re.I)
COMPANY_NAME = re.compile(r"\b([A-Z0-9][A-Z0-9&'.,\- ]{2,80}?\s(?:LIMITED|LTD|LLP|PLC))\b")


def _get(url, params=None, tries=5):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"GOV.UK: gave up on {url}")


def press_releases(since):
    res = _get(SEARCH, {
        "filter_organisations": "insolvency-service",
        "filter_format": "press_release",
        "filter_public_timestamp": f"from:{since}",
        "order": "-public_timestamp",
        "count": 500,
        "fields": "title,public_timestamp,link",
    })
    rows = []
    for r in res["results"]:
        body = _get(CONTENT + r["link"])["details"].get("body", "")
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        rows.append({
            "date": r["public_timestamp"][:10],
            "title": r["title"],
            "url": "https://www.gov.uk" + r["link"],
            "wound_up": bool(WOUND_UP.search(r["title"] + " " + text[:600])),
            "covid": bool(COVID.search(r["title"] + " " + text)),
            "company_numbers": sorted(set(COMPANY_NUMBER.findall(text))),
            "company_names": sorted(set(n.strip() for n in COMPANY_NAME.findall(text))),
            "text": text,
        })
    return rows


def candidates(rows):
    """Wound-up companies from non-Covid releases, one row per named company."""
    out = []
    for r in rows:
        if not r["wound_up"] or r["covid"]:
            continue
        for name in r["company_names"] or [None]:
            out.append({"channel": "scam_wound_up", "exposed_on": r["date"], "name": name,
                        "company_numbers_in_source": r["company_numbers"], "source_url": r["url"],
                        "source_title": r["title"]})
    return out
