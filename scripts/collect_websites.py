"""Add each pilot company's own website to its case (SPEC.md 3, `web`), frozen at as_of.

1. Candidates: hosts in the company's search results (Google links already collected), minus
   registry mirrors, directories and social sites.
2. A candidate is the company's site when its host matches the company name and the Wayback copy
   of its homepage on or before as_of names the company (or shows its company number).
3. The case gets: the URL (also stated in the application, as an applicant would), the archived
   homepage text, the capture date, and the domain's registration date (RDAP). A domain whose
   current registration post-dates as_of is rejected: it is not the site that existed then.
4. Archived pages that come back nearly empty (sites built with heavy scripting) are listed in
   data/pilot/search/websites_needing_render.json for rendering in a browser.

    .venv/bin/python scripts/collect_websites.py
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_search import SKIP, _SUFFIX, _norm, mentions  # noqa: E402
from kybbench.sources import brave, rdap, serpapi, wayback  # noqa: E402

PILOT = Path(os.environ.get("KYB_SPLIT", "data/pilot"))  # which split to fill
NOT_OWN_SITE = re.compile(
    r"(company-information\.service\.gov\.uk|gov\.uk|endole|tinytax|companycheck|opencorporates|datocapital|bizdb|"
    r"companieslist|find-open|yell\.com|192\.com|checkatrade|trustpilot|wikipedia|scribd|issuu|companyhub|"
    r"northdata|dnb\.com|bloomberg|crunchbase|glassdoor|indeed|reed\.co\.uk|thegazette|parliament\.uk|"
    r"theyworkforyou|google\.|bing\.|amazon\.|ebay\.|wired-gov|instagram|facebook|linkedin)")
MIN_TEXT = 300  # below this, the archived page probably needs a browser to render


FOREIGN = re.compile(r"\.(?!uk$|com$|net$|org$|io$|co$|biz$|info$|london$|scot$|wales$)[a-z]{2,}$")


def host_matches(host, name):
    label = re.sub(r"^www\d?\.", "", host).split(".")[0].replace("-", "")
    words = _norm(_SUFFIX.sub("", name)).split()
    for joined in {"".join(words), "".join(w for w in words if w != "and")}:
        if joined and (SequenceMatcher(None, label, joined).ratio() >= 0.8
                       or (len(label) >= 6 and (label in joined or joined in label))):
            return True
    return False


def needs_number(host, created, incorporated):
    """Namesake guard: an older domain, or another country's, must show the company number."""
    old = bool(created and incorporated and created < f"{int(incorporated[:4]) - 1}{incorporated[4:]}")
    return old or bool(FOREIGN.search(host.removesuffix(".uk.com")))


def candidates(case, google_links):
    name = case["registry"]["name"]
    core = _SUFFIX.sub("", name).strip(" .,")
    urls = list(google_links)
    for q in (f'"{name}"', f'"{core}"'):
        # reuse searches already made (Google via SerpAPI, and Brave); never spends new searches
        for cached in (serpapi.CACHE_DIR / (re.sub(r"[^A-Za-z0-9]+", "_", q)[:180] + ".json"),
                       brave.CACHE_DIR / (re.sub(r"[^A-Za-z0-9]+", "_", f"{q}_None")[:180] + ".json")):
            if cached.exists():
                urls += json.loads(cached.read_text())
    hosts = []
    for u in urls:
        host = (urlparse(u).hostname or "").lower()
        if host and not SKIP.search(host) and not NOT_OWN_SITE.search(host) and host_matches(host, name) and host not in hosts:
            hosts.append(host)
    return hosts


POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")


def postcode(text):
    m = POSTCODE.search((text or "").upper())
    return f"{m.group(1)} {m.group(2)}" if m else None


def shows_postcode(text, pc):
    return bool(pc) and re.search(pc.replace(" ", r"\s*"), text.upper()) is not None


def website_for(case, google_links):
    name, number, as_of = case["registry"]["name"], case["registry"]["company_number"], case["as_of"]
    pc = postcode(case["registry"].get("registered_address"))
    for host in candidates(case, google_links):
        domain = re.sub(r"^www\d?\.", "", host)
        created = rdap.registered(domain)
        if created and created > as_of:
            continue
        cap = wayback.capture_before(f"{host}/", as_of)
        if not cap:
            continue
        text = wayback.page_text(*cap)
        if len(text) < MIN_TEXT:
            return {"url": f"https://{host}/", "needs_render": True, "capture": cap, "domain_created": created}
        if needs_number(host, created, case["registry"]["incorporated"]):
            ok = number in text
        else:  # the host already matches the name; the page must also name the company or show its details
            ok = mentions(text, name) or number in text or shows_postcode(text, pc)
        if ok:
            ts = cap[0]
            return {"url": f"https://{host}/", "domain_created": created, "text": text,
                    "captured": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "archived": f"https://web.archive.org/web/{ts}/{cap[1]}",
                    "fetched_from": "wayback"}
    return None


def main():
    gl = PILOT / "search/google_links.jsonl"
    google = {r["id"]: r["urls"] for r in map(json.loads, open(gl)) if not r.get("sorry")} if gl.exists() else {}
    cases = [json.loads(l) for l in open(PILOT / "cases.jsonl")]
    with ThreadPoolExecutor(4) as ex:
        found = list(ex.map(lambda c: website_for(c, google.get(c["case_id"], [])), cases))
    render = []
    for c, w in zip(cases, found):
        if w and w.get("needs_render"):
            render.append({"case_id": c["case_id"], **w})
            w = None
        c["web"] = w
        c["application"]["website"] = w["url"] if w else None
        print(c["case_id"], w["url"] if w else "-", flush=True)
    (PILOT / "cases.jsonl.tmp").write_text("".join(json.dumps(x) + "\n" for x in cases))
    (PILOT / "cases.jsonl.tmp").replace(PILOT / "cases.jsonl")
    (PILOT / "search/websites_needing_render.json").write_text(json.dumps(render, indent=1))
    print(f"websites: {sum(1 for w in found if w and not w.get('needs_render'))}/{len(cases)} | need browser render: {len(render)}")


if __name__ == "__main__":
    main()
