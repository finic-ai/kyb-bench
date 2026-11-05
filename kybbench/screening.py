"""Sanctions and PEP screening for case files, returning candidates the way a screening vendor
would: every plausible name match, including different people with the same name.

Sanctions: UK Sanctions List (FCDO) and OFAC SDN, downloaded to data/cache/sanctions/.
Entries designated after the case date are dropped where the list gives a designation date.
PEPs: Wikidata people holding a position (P39), found by name search.
"""

import csv
import difflib
import json
import re
import time
from functools import lru_cache
from pathlib import Path

import requests

SANCTIONS_DIR = Path("data/cache/sanctions")
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "kybbench/0.1 (+https://kyb-bench.vercel.app)"}
CACHE_DIR = Path("data/cache/wikidata")
_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "sir", "dame", "lord", "lady", "baroness", "baron", "viscount",
               "earl", "prof", "the", "rt", "hon", "mp", "kc", "qc", "obe", "mbe", "cbe"}


def normalise(name):
    name = re.sub(r"[^a-z ]", " ", (name or "").lower())
    return [t for t in name.split() if t not in _HONORIFICS and len(t) > 1]


def similar(a, b):
    ta, tb = normalise(a), normalise(b)
    if not ta or not tb:
        return 0.0
    if set(ta) <= set(tb) or set(tb) <= set(ta):
        return 0.95 if min(len(ta), len(tb)) >= 2 else 0.6
    return difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()


def _uk_date(s):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


@lru_cache(maxsize=1)
def sanctions_entries():
    entries = []
    with open(SANCTIONS_DIR / "uk_sanctions_list.csv", newline="", encoding="utf-8-sig") as f:
        next(f)  # report date line
        for row in csv.DictReader(f):
            parts = [row.get(f"Name {i}", "") for i in (1, 2, 3, 4, 5, 6)]
            name = " ".join(p.strip() for p in parts if p and p.strip())
            if name:
                entries.append({"name": name, "list": "UK Sanctions List", "type": row.get("Designation Type"),
                                "designated": _uk_date(row.get("Date Designated")), "dob": row.get("D.O.B") or None,
                                "nationality": row.get("Nationality(/ies)") or None, "regime": row.get("Regime Name")})
    with open(SANCTIONS_DIR / "ofac_sdn.csv", newline="", encoding="latin-1") as f:
        for row in csv.reader(f):
            if len(row) < 12:
                continue
            name = row[1].strip()
            if "," in name and row[2].strip().lower() == "individual":
                last, first = name.split(",", 1)
                name = f"{first.strip()} {last.strip()}"
            dob = re.search(r"DOB ([^;]+);", row[11])
            entries.append({"name": name, "list": "OFAC SDN", "type": row[2].strip("- ") or "entity",
                            "designated": None, "dob": dob.group(1).strip() if dob else None,
                            "nationality": None, "regime": row[3]})
    return entries


@lru_cache(maxsize=1)
def _sanctions_index():
    index = {}
    for i, e in enumerate(sanctions_entries()):
        for t in set(normalise(e["name"])):
            index.setdefault(t, []).append(i)
    return index


def screen_sanctions(name, as_of, threshold=0.85):
    entries, index = sanctions_entries(), _sanctions_index()
    seen = set()
    for t in normalise(name):
        seen.update(index.get(t, []))
    out = []
    for i in seen:
        e = entries[i]
        if e["designated"] and e["designated"] > as_of:
            continue
        s = similar(name, e["name"])
        if s >= threshold:
            out.append({**e, "similarity": round(s, 2)})
    return sorted(out, key=lambda e: -e["similarity"])[:5]


def _get(url, params, cache_key):
    cached = CACHE_DIR / f"{re.sub(r'[^A-Za-z0-9]+', '_', cache_key)[:150]}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    for attempt in range(10):
        time.sleep(0.3)  # stay well under Wikidata's rate limits
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                body = r.json()
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(body))
                return body
            retry = r.headers.get("retry-after", "")
            time.sleep(int(retry) + 1 if retry.isdigit() else min(60, 2 ** attempt))
        except requests.RequestException:
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"Wikidata: gave up on {cache_key}")


def _positions(qids):
    if not qids:
        return {}
    values = " ".join(f"wd:{q}" for q in qids)
    query = f"""
    SELECT ?p ?pLabel ?posLabel ?start ?end ?dob WHERE {{
      VALUES ?p {{ {values} }}
      ?p wdt:P31 wd:Q5; p:P39 ?st. ?st ps:P39 ?pos.
      OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }} OPTIONAL {{ ?p wdt:P569 ?dob }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    body = _get(SPARQL, {"query": query, "format": "json"}, "pos_" + "_".join(sorted(qids)))
    out = {}
    for b in body["results"]["bindings"]:
        q = b["p"]["value"].rsplit("/", 1)[1]
        out.setdefault(q, {"name": b["pLabel"]["value"], "dob": b.get("dob", {}).get("value", "")[:10] or None, "positions": []})
        out[q]["positions"].append({"position": b["posLabel"]["value"],
                                    "from": b.get("start", {}).get("value", "")[:10] or None,
                                    "to": b.get("end", {}).get("value", "")[:10] or None})
    return out


def screen_pep(name, as_of, threshold=0.85):
    """Wikidata people with the same or a very similar name who held a position by as_of."""
    terms = normalise(name)
    if len(terms) < 2:
        return []
    query = f"{terms[0]} {terms[-1]}"
    found = _get(WIKIDATA_API, {"action": "wbsearchentities", "search": query, "language": "en",
                                "type": "item", "limit": 20, "format": "json"}, "search_" + query)
    qids = [r["id"] for r in found.get("search", []) if similar(name, r.get("label", "")) >= threshold]
    out = []
    # PEP status lapses some years after leaving office; ignore people born before 1925
    recent = f"{int(as_of[:4]) - 5}{as_of[4:]}"
    for q, p in _positions(tuple(qids)).items():
        if p["dob"] and p["dob"] < "1925":
            continue
        held = [x for x in p["positions"]
                if (not x["from"] or x["from"] <= as_of) and (not x["to"] or x["to"] >= recent)]
        if held:
            out.append({"name": p["name"], "wikidata": q, "dob": p["dob"], "positions": held[:5]})
    return out
