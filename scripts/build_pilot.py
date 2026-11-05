"""Build the 100-company UK pilot set (SPEC.md 10, step 1).

Groups:
    bad       fake or front companies from the Insolvency Service channel (fit and borderline)
    review    companies the registrar later moved to the default address (RP05), fresh window
    pep       companies with a sitting MP as a director (Wikidata + Companies House, DOB matched)
    industry  companies registered in high-risk financial and gambling SIC codes
    clean     ordinary active companies; 20 of them get planted issues

Each case is frozen at a snapshot date as_of: 90 days before the first public sign for bad and
review cases, otherwise a random date between 2026-04-01 and 2026-07-31. Websites and search
results are added in a second pass.

    set -a; . ./.env; set +a; .venv/bin/python scripts/build_pilot.py
"""

import datetime as dt
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import companies_house as ch, screening  # noqa: E402
from kybbench.plant import clean_application, plant  # noqa: E402
from kybbench.sources import fca, gazette, registrar  # noqa: E402

OUT = Path("data/pilot")
SEED = 7
N = {"review": 15, "pep": 5, "industry": 10}
N_CLEAN, N_PLANTED = 51, 20
WINDOW_FROM = "2026-08-03"
HIGH_RISK_SIC = {"64999": "H_INVESTMENT", "66190": "H_INVESTMENT", "66300": "H_INVESTMENT",
                 "64921": "H_LENDING", "64929": "H_LENDING", "66120": "H_INVESTMENT", "92000": "H_GAMBLING"}
PLANTABLE = ["OWNER_MISMATCH", "DIRECTOR_MISMATCH", "DISQUALIFIED_DIRECTOR", "SANCTIONS_HIT",
             "ACTIVITY_MISMATCH", "VOLUME_IMPLAUSIBLE"]

rng = random.Random(SEED)
nrng = np.random.default_rng(SEED)


def days(d, n):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()


def random_as_of(incorporated):
    lo = max(dt.date(2026, 4, 1), dt.date.fromisoformat(incorporated) + dt.timedelta(days=90))
    hi = dt.date(2026, 7, 31)
    return (lo + dt.timedelta(days=rng.randrange(max(1, (hi - lo).days)))).isoformat() if lo < hi else None


def person(name):
    """'SMITH, Jane Mary' -> 'Jane Mary Smith'; drops honorifics."""
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip().title()}"
    parts = [p for p in name.replace(",", " ").split() if p.lower().strip(".") not in screening._HONORIFICS]
    return " ".join(parts)


# ---- sampling --------------------------------------------------------------------------------

def bad_cases():
    out = []
    for c in json.load(open("data/labels/candidates_scam_wound_up.json"))["candidates"]:
        if c["verdict"] not in ("fit", "borderline"):
            continue
        for chk in c.get("checks", []):
            first = (chk.get("gazette_first_trouble") or {}).get("date") or c["exposed_on"]
            as_of = days(first, -90)
            ceased = (ch.company(chk["company_number"]) or {}).get("date_of_cessation")
            if ceased and ceased <= as_of:
                as_of = days(ceased, -90)  # a dissolved company cannot apply
            out.append({"number": chk["company_number"], "as_of": as_of,
                        "label": {"decision": "bad", "issues": [], "slice": "real", "channel": "scam_wound_up",
                                  "set": chk["set"], "verdict": c["verdict"], "exposed_on": first,
                                  "source": c["source_url"]}})
    return out


def review_cases():
    rows = [json.loads(l) for l in open("data/labels/raw/rp05_dates.jsonl")]
    fresh = [r for r in rows if r["rp05"] and r["rp05"] >= WINDOW_FROM and r.get("incorporated")]
    out = []
    for r in rng.sample(fresh, len(fresh)):
        as_of = days(r["rp05"], -90)
        if as_of < days(r["incorporated"], 60):
            continue
        out.append({"number": r["company_number"], "as_of": as_of,
                    "label": {"decision": "review", "issues": [], "slice": "real", "channel": "registrar_action",
                              "set": "fresh", "exposed_on": r["rp05"]}})
        if len(out) == N["review"]:
            return out
    return out


def mps():
    q = """SELECT ?p ?pLabel ?dob WHERE { ?p p:P39 ?s. ?s ps:P39 wd:Q77685926. OPTIONAL { ?p wdt:P569 ?dob }
           SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }"""
    body = screening._get(screening.SPARQL, {"query": q, "format": "json"}, "mps_q77685926")
    return [{"name": b["pLabel"]["value"], "qid": b["p"]["value"].rsplit("/", 1)[1],
             "dob": b.get("dob", {}).get("value", "")[:7]} for b in body["results"]["bindings"] if b.get("dob")]


def pep_cases():
    out, seen = [], set()
    for mp in rng.sample(mps(), 120):
        y, m = mp["dob"].split("-")
        for o in ch.search_officers(mp["name"]):
            dob = o.get("date_of_birth") or {}
            if (str(dob.get("year")), f"{dob.get('month', 0):02d}") != (y, m) or screening.similar(o.get("title", ""), mp["name"]) < 0.85:
                continue
            link = o.get("links", {}).get("self")
            for a in ch.officer_appointments(link) if link else []:
                to = a.get("appointed_to", {})
                num = to.get("company_number")
                if a.get("resigned_on") or to.get("company_status") != "active" or a.get("officer_role") != "director" or num in seen:
                    continue
                prof = ch.company(num) or {}
                as_of = random_as_of(max(prof.get("date_of_creation", "9999"), a.get("appointed_on") or ""))
                if not as_of:
                    continue
                seen.add(num)
                out.append({"number": num, "as_of": as_of,
                            "label": {"decision": "review", "issues": [], "slice": "real", "channel": "pep",
                                      "set": "fresh", "pep": {"name": mp["name"], "wikidata": mp["qid"]}}})
                break
            break
        if len(out) == N["pep"]:
            return out
    return out


def _random_companies(n, sic=None, exclude=()):
    out = []
    tries = 0
    while len(out) < n and tries < n * 20:
        tries += 1
        day = dt.date(2022, 1, 1) + dt.timedelta(days=rng.randrange(365 * 4))
        params = {"company_status": "active", "company_type": "ltd", "size": 100,
                  "incorporated_from": day.isoformat(), "incorporated_to": (day + dt.timedelta(days=30 if sic else 0)).isoformat()}
        if sic:
            params["sic_codes"] = sic
        items = (ch._get("/advanced-search/companies", params) or {}).get("items", [])
        items = [i for i in items if i["company_number"] not in exclude
                 and registrar.DEFAULT_POSTCODE not in str(i.get("registered_office_address", {}))]
        if not items:
            continue
        c = rng.choice(items)
        num = c["company_number"]
        if registrar.default_address_applied(num) or gazette.earliest_trouble(num):
            continue
        as_of = random_as_of(c["date_of_creation"])
        if as_of:
            out.append((c, as_of))
            exclude = set(exclude) | {num}
    return out


def industry_cases(exclude):
    out = []
    sics = list(HIGH_RISK_SIC)
    for i in range(N["industry"]):
        got = _random_companies(1, sic=sics[i % len(sics)], exclude=exclude)
        for c, as_of in got:
            exclude = set(exclude) | {c["company_number"]}
            sic = sics[i % len(sics)]
            out.append({"number": c["company_number"], "as_of": as_of,
                        "label": {"decision": "review", "issues": [], "slice": "real", "channel": "industry",
                                  "set": "fresh", "industry": HIGH_RISK_SIC[sic],
                                  "needs_human_label": ["industry", "licence"]}})
    return out


def clean_cases(exclude):
    return [{"number": c["company_number"], "as_of": as_of,
             "label": {"decision": "good", "issues": [], "slice": "real", "channel": "none", "set": "fresh",
                       "needs_human_label": ["industry"]}}
            for c, as_of in _random_companies(N_CLEAN, exclude=exclude)]


# ---- case assembly ---------------------------------------------------------------------------

def screen(case):
    app, reg = case["application"], case["registry"]
    people = {person(d["name"]) for d in app["directors"]} | {person(o["name"]) for o in app["owners"]}
    people |= {person(o["name"]) for o in reg.get("officers") or []} | {person(p["name"]) for p in reg.get("psc") or []
                                                                         if "individual" in (p.get("kind") or "")}
    people.discard("")
    names = sorted(people) + [reg["name"]]
    case["screening"] = {
        "sanctions": [{"screened": n, "candidates": screening.screen_sanctions(n, case["as_of"])} for n in names],
        "pep": [{"screened": n, "candidates": screening.screen_pep(n, case["as_of"])} for n in sorted(people)],
        "disqualified_directors": [{"screened": n, "candidates": [
            {"name": d.get("title"), "date_of_birth": d.get("date_of_birth"), "address": d.get("address_snippet")}
            for d in ch.search_disqualified(n)[:5] if screening.similar(d.get("title", ""), n) >= 0.85]}
            for n in sorted(person(d["name"]) for d in app["directors"])],
    }
    case["licences"] = {"fca": [m for m in fca.search(reg["name"]) if fca.normalise(m.get("Name")) == fca.normalise(reg["name"])],
                        "gambling_commission": None, "hmrc_msb": None}


SEVERITY = {"good": 0, "review": 1, "bad": 2}


def confirm(case, label):
    """Confirm PEP and disqualified-director hits by matching month and year of birth with the
    registry, and raise the label's decision to match. Planted hits are already in the label."""
    dob = {person(o["name"]): o.get("dob_month") for o in case["registry"].get("officers") or []}
    peps = [{"name": s["screened"], "wikidata": c["wikidata"]} for s in case["screening"]["pep"]
            for c in s["candidates"] if dob.get(s["screened"]) and (c.get("dob") or "")[:7] == dob[s["screened"]]]
    disq = [s["screened"] for s in case["screening"]["disqualified_directors"]
            for c in s["candidates"] if dob.get(s["screened"])
            and (str(c.get("date_of_birth") or ""))[:7] == dob[s["screened"]]]
    label["pep_confirmed"] = peps
    label["disqualified_confirmed"] = sorted(set(disq))
    if disq and "DISQUALIFIED_DIRECTOR" not in label["issues"]:
        label["issues"] = label["issues"] + ["DISQUALIFIED_DIRECTOR"]
    floor = "bad" if disq else "review" if peps else "good"
    if SEVERITY[floor] > SEVERITY[label["decision"]]:
        label["decision"] = floor
    return label


def build(entry):
    reg = ch.snapshot(entry["number"], entry["as_of"])
    case = {"case_id": None, "as_of": entry["as_of"], "jurisdiction": "GB", "registry": reg,
            "web": None, "documents": [], "search": None}
    case["application"] = clean_application(case)
    for d in case["application"]["directors"]:
        d["name"] = person(d["name"])
    for o in case["application"]["owners"]:
        o["name"] = person(o["name"])
    return case


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    entries = bad_cases()
    print("bad", len(entries), flush=True)
    entries += review_cases(); print("+review", len(entries), flush=True)
    entries += pep_cases(); print("+pep", len(entries), flush=True)
    taken = {e["number"] for e in entries}
    entries += industry_cases(taken); print("+industry", len(entries), flush=True)
    taken = {e["number"] for e in entries}
    entries += clean_cases(taken); print("+clean", len(entries), flush=True)

    cases, labels = [], {}
    for e in entries:
        try:
            cases.append((build(e), e["label"]))
        except Exception as err:
            print(f"skip {e['number']}: {err}", flush=True)

    # planting pools come from the clean companies themselves and public lists
    pool = {
        "names": sorted({d["name"] for c, l in cases if l["channel"] == "none" for d in c["application"]["directors"]}),
        "disqualified": sorted({person(d["title"]) for s in ("Smith", "Khan", "Patel", "Jones", "Ali", "Brown")
                                for d in ch.search_disqualified(s)[:20] if d.get("title")}),
        "sanctioned": [e["name"] for e in screening.sanctions_entries()
                       if e["list"] == "UK Sanctions List" and (e["type"] or "").lower() == "individual"][:400],
        "sites": [], "industries": ["47910", "64999", "92000", "66190", "46900", "56101", "68100", "62020"],
    }
    clean_idx = [i for i, (c, l) in enumerate(cases) if l["channel"] == "none"]
    for i in rng.sample(clean_idx, min(N_PLANTED, len(clean_idx))):
        c, _ = cases[i]
        codes = rng.sample(PLANTABLE, rng.choice([1, 1, 2]))
        planted_case, lab = plant(c, codes, pool, nrng)
        lab.update({"channel": "planted", "set": "fresh", "needs_human_label": ["industry"]})
        cases[i] = (planted_case, lab)

    rng.shuffle(cases)
    with open(OUT / "cases.jsonl", "w") as f:
        for n, (c, l) in enumerate(cases, 1):
            c["case_id"] = f"pilot-{n:03d}"
            screen(c)
            labels[c["case_id"]] = confirm(c, {**l, "company_number": c["registry"]["company_number"]})
            f.write(json.dumps(c) + "\n")
            if n % 10 == 0:
                print("screened", n, flush=True)
    json.dump(labels, open(OUT / "labels.json", "w"), indent=1)
    summary = {}
    for l in labels.values():
        key = f"{l['channel']}/{l['decision']}"
        summary[key] = summary.get(key, 0) + 1
    print(json.dumps(summary, indent=1))




def rebuild():
    """Rebuild the existing pilot's case files in place (same companies, same as_of dates) after a
    fix to the registry rebuild or screening. Planted applications are kept as they are."""
    old = [json.loads(l) for l in open(OUT / "cases.jsonl")]
    labels = json.load(open(OUT / "labels.json"))
    with open(OUT / "cases.jsonl.tmp", "w") as f:
        for n, c in enumerate(old, 1):
            lab = labels[c["case_id"]]
            new = build({"number": c["registry"]["company_number"], "as_of": c["as_of"]})
            new["case_id"] = c["case_id"]
            if lab["channel"] == "planted":
                new["application"] = c["application"]
            if lab["channel"] == "industry":
                lab["pending"] = "industry and licence labels"
            screen(new)
            labels[c["case_id"]] = confirm(new, lab)
            f.write(json.dumps(new) + "\n")
            if n % 20 == 0:
                print("rebuilt", n, flush=True)
    (OUT / "cases.jsonl.tmp").replace(OUT / "cases.jsonl")
    json.dump(labels, open(OUT / "labels.json", "w"), indent=1)


if __name__ == "__main__":
    rebuild() if "--rebuild" in sys.argv else main()
