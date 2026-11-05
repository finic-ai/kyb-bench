"""Add frozen search results to pilot cases (SPEC.md 3, `search`).

For each case: search the company name, with and without its Ltd/Limited suffix (Google via SerpAPI, plus
any Google links already collected in Chrome), keep only links with a Wayback capture on or before as_of whose
captured text mentions the company by name, and build each result from that capture:
title and a snippet around the first mention of the company name, the capture date as
`published`, and the capture URL as `archived`. Live titles and snippets are never used.

    set -a; . ./.env; set +a; .venv/bin/python scripts/collect_search.py
"""

import json
import os
import re
import sys
import threading
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench.sources import serpapi, wayback  # noqa: E402

PILOT = Path(os.environ.get("KYB_SPLIT", "data/pilot"))  # which split to fill
MAX_RESULTS = 8
MAX_LINKS = 12  # links checked per case, in search order
SECOND_QUERY_BELOW = 5  # run the suffix-free query only when the full-name query returns fewer links
# Sites the Wayback Machine rarely stores, or that need a login: checking them wastes lookups
SKIP = re.compile(r"(^|\.)(linkedin|facebook|instagram|x|twitter|tiktok|youtube|pinterest|rocketreach|zoominfo|"
                  r"signalhire|contactout|apollo)\.(com|io)$"
                  # Companies House pages: almost never archived per company, and the case already
                  # holds the registry record as of the case date
                  r"|(^|\.)company-information\.service\.gov\.uk$")
# Cases in flight at once. Wayback lookups back off automatically when throttled; raise with care.
WORKERS = int(os.environ.get("KYB_SEARCH_WORKERS", "4"))
_SUFFIX = re.compile(r"\b(limited|ltd|llp|plc)\b\.?", re.I)


# Sites that never produced a usable capture in earlier collections (data/search_skip_sites.json)
SKIP_SITES = set(json.loads(Path("data/search_skip_sites.json").read_text())["sites"]) if Path("data/search_skip_sites.json").exists() else set()


def site(url):
    return re.sub(r"^(www\d?|m|uk)\.", "", (urlparse(url).hostname or "").lower())


def worth_looking_up(url):
    host = urlparse(url).hostname or ""
    return bool(host) and not SKIP.search(host) and site(url) not in SKIP_SITES


def snippet(text, name, width=300):
    core = _SUFFIX.sub("", name).strip()
    i = text.lower().find(core.lower()) if core else -1
    if i < 0:
        return text[:width]
    start = max(0, i - width // 3)
    return ("..." if start else "") + text[start:start + width]


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("&", " and ")).strip()


def mentions(text, name):
    """Whether the captured text names the company. Search engines match pages on their current
    content, so a page can be selected only because it now mentions the outcome; requiring the
    name in the capture removes those (and unrelated namesake noise)."""
    core = _norm(_SUFFIX.sub("", name))
    return bool(core) and f" {core} " in f" {_norm(text)} "


def results_for(case, google_links):
    name, as_of = case["registry"]["name"], case["as_of"]
    core = _SUFFIX.sub("", name).strip(" .,")
    query = f'"{name}"'
    found = serpapi.search(query)
    if len(found) < SECOND_QUERY_BELOW and core and core != name:
        found += serpapi.search(f'"{core}"')
    links = [u for u in dict.fromkeys(google_links + found) if worth_looking_up(u)][:MAX_LINKS]
    out = []
    for url in links:
        cap = wayback.capture_before(url, as_of)
        if not cap:
            continue
        ts, original = cap
        text = wayback.page_text(ts, original)
        if not text or not mentions(text, name):
            continue
        title = text.split(" | ", 1)[0][:200] if " | " in text else original
        out.append({"title": title, "url": original, "snippet": snippet(text, name),
                    "published": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
                    "archived": f"https://web.archive.org/web/{ts}/{original}"})
        if len(out) == MAX_RESULTS:
            break
    return {"query": query, "results": out, "note": "frozen at as_of from Wayback captures; live snippets not used"}


def main():
    google = {}
    gl = PILOT / "search/google_links.jsonl"
    if gl.exists():
        google = {r["id"]: r["urls"] for r in map(json.loads, open(gl)) if not r.get("sorry")}
    cases = [json.loads(l) for l in open(PILOT / "cases.jsonl")]
    lock = threading.Lock()

    def save():
        (PILOT / "cases.jsonl.tmp").write_text("".join(json.dumps(x) + "\n" for x in cases))
        (PILOT / "cases.jsonl.tmp").replace(PILOT / "cases.jsonl")

    with ThreadPoolExecutor(WORKERS) as ex:
        futures = {ex.submit(results_for, c, google.get(c["case_id"], [])): c for c in cases}
        for n, fut in enumerate(as_completed(futures), 1):
            c = futures[fut]
            with lock:
                c["search"] = fut.result()
                print(f"{n}/{len(cases)} {c['case_id']}: {len(c['search']['results'])} results", flush=True)
                if n % 10 == 0:  # checkpoint
                    save()
    save()


if __name__ == "__main__":
    main()
