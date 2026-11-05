"""Common Crawl: a second web archive, checked when the Wayback Machine has no capture on or
before the case date.

NOT USED in the pipeline (2026-10-28): on a random sample of 30 pilot links the Wayback Machine
had no pre-case-date capture of, Common Crawl had none either (0/30). The Wayback Machine ingests
Common Crawl's data, so the two overlap almost entirely. Kept for reference. Same rule as Wayback: only a capture made on or before as_of is used, and
its text comes from the stored page, never the live site.

Index: https://index.commoncrawl.org (one CDX endpoint per crawl). Records are fetched by byte
range from https://data.commoncrawl.org. Free, no key.
"""

import gzip
import html
import json
import re
import time
from functools import lru_cache
from pathlib import Path

import requests

INDEX = "https://index.commoncrawl.org"
DATA = "https://data.commoncrawl.org/"
HEADERS = {"User-Agent": "kybbench/0.1 (+https://kyb-bench.vercel.app)"}
CACHE_DIR = Path("data/cache/commoncrawl")
MAX_CRAWLS = 8  # most recent crawls before the case date to check (about a year and a half)


def _get(url, params=None, headers=None, tries=5, timeout=60):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=timeout)
            if r.status_code in (200, 206):
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(min(60, 3 * 2 ** attempt))
    return None


@lru_cache(maxsize=1)
def crawls():
    """[(crawl id, first capture date YYYY-MM-DD)], newest first."""
    out = []
    for c in _get(f"{INDEX}/collinfo.json").json():
        start = (c.get("from") or "")[:10]
        out.append((c["id"], start))
    return out


def capture_before(url, as_of):
    """The latest successful capture of url on or before as_of across recent crawls, or None.
    Returns {"timestamp", "url", "filename", "offset", "length"}."""
    key = re.sub(r"[^A-Za-z0-9]+", "_", f"{url}_{as_of}")[:180]
    cached = CACHE_DIR / f"idx_{key}.json"
    if cached.exists():
        return json.loads(cached.read_text()) or None
    stamp = as_of.replace("-", "")
    best = None
    for crawl, start in [c for c in crawls() if c[1] and c[1] <= as_of][:MAX_CRAWLS]:
        r = _get(f"{INDEX}/{crawl}-index", {"url": url, "output": "json"})
        if r is None or not r.text.strip():
            continue
        rows = [json.loads(l) for l in r.text.splitlines() if l.strip()]
        rows = [x for x in rows if x.get("status") == "200" and x["timestamp"][:8] <= stamp]
        if rows:
            best = max(rows, key=lambda x: x["timestamp"])
            best = {k: best[k] for k in ("timestamp", "url", "filename", "offset", "length")}
            break
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(best))
    return best


def page_text(cap, max_chars=20000):
    key = re.sub(r"[^A-Za-z0-9]+", "_", f"{cap['timestamp']}_{cap['url']}")[:180]
    cached = CACHE_DIR / f"page_{key}.txt"
    if cached.exists():
        return cached.read_text()
    start, length = int(cap["offset"]), int(cap["length"])
    r = _get(DATA + cap["filename"], headers={"Range": f"bytes={start}-{start + length - 1}"})
    text = ""
    if r is not None:
        try:
            record = gzip.decompress(r.content).decode("utf-8", "replace")
            body = record.split("\r\n\r\n", 2)[-1]  # WARC headers, HTTP headers, then the page
            body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
            title = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.S | re.I)
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
            if title:
                text = html.unescape(title.group(1).strip()) + " | " + text
        except (OSError, ValueError):
            text = ""
    text = text[:max_chars]
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text)
    return text
