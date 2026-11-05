"""FCA Financial Services Register: name lookup, with a disk cache.

The Register API finds firms by name only. Firms on the FCA Warning List come back with status
"Unauthorised" and type "Unauthorised firm", but with no warning date and no detail record, so
the warning date has to be read from the FCA website for any match.

Key: https://register.fca.org.uk/Developer/s/ -> FCA_API_EMAIL and FCA_API_KEY.
"""

import json
import os
import re
import time
from pathlib import Path

import requests

BASE = "https://register.fca.org.uk/services/V0.1"
CACHE_DIR = Path("data/cache/fca")
MIN_INTERVAL = 1.1  # published limits vary between 10 per 10 s and 100 per 60 s

_last = 0.0
_session = requests.Session()
_SUFFIX = re.compile(r"\b(limited|ltd|llp|plc|uk|the|company|co)\b")
_POSTCODE = re.compile(r"\s*\(Postcode:\s*([^)]*)\)\s*$")


def normalise(name):
    name = _POSTCODE.sub("", name or "").lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", name)).strip()


def search(name, cache_dir=CACHE_DIR):
    global _last
    cached = Path(cache_dir) / (re.sub(r"[^A-Za-z0-9]+", "_", name)[:120] + ".json")
    if cached.exists():
        return json.loads(cached.read_text())
    headers = {"X-Auth-Email": os.environ["FCA_API_EMAIL"], "X-Auth-Key": os.environ["FCA_API_KEY"],
               "Content-Type": "application/json"}
    for attempt in range(8):
        wait = _last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        try:
            r = _session.get(f"{BASE}/Search", params={"q": name, "type": "firm"}, headers=headers, timeout=30)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            data = r.json().get("Data") or []
            break
        if r is not None and r.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"FCA {r.status_code} for {name!r}: {r.text[:200]}")
        time.sleep(min(120, 5 * 2 ** attempt))
    else:
        raise RuntimeError(f"FCA: gave up on {name!r}")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data))
    return data


def unauthorised_matches(name):
    """Register entries marked Unauthorised whose name matches `name` after normalising."""
    target = normalise(name)
    out = []
    for row in search(name):
        if row.get("Status") != "Unauthorised":
            continue
        postcode = _POSTCODE.search(row.get("Name", ""))
        out.append({
            "fca_name": _POSTCODE.sub("", row["Name"]).strip(),
            "fca_postcode": postcode.group(1).strip() if postcode else None,
            "exact": normalise(row["Name"]) == target,
        })
    return out
