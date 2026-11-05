"""Build the validation split (SPEC.md 4.3): the only labelled data any system may use for tuning.

Same groups as the pilot, all historical (exposed before the fresh window), no pilot company
reused, and ordinary companies matched to the other groups by incorporation date and case date,
so neither company age nor case date can stand in for the label.

    set -a; . ./.env; set +a; .venv/bin/python scripts/build_validation.py
"""

import datetime as dt
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pilot as bp  # noqa: E402
from kybbench import companies_house as ch  # noqa: E402
from kybbench.plant import plant  # noqa: E402
from kybbench.sources import gazette, registrar  # noqa: E402

OUT = Path("data/validation")
WINDOW_FROM = "2026-08-03"
N = {"review": 40, "pep": 15, "industry": 30, "clean": 110, "planted": 60}
rng = random.Random(11)
nrng = np.random.default_rng(11)
bp.rng = rng  # the pilot helpers sample with this
PILOT = {json.loads(l)["registry"]["company_number"] for l in open("data/pilot/cases.jsonl")}


def bad_cases():
    out = []
    for c in json.load(open("data/labels/candidates_scam_wound_up_historical.json"))["candidates"]:
        if c["verdict"] not in ("fit", "borderline"):
            continue
        for chk in c.get("checks", []):
            num = chk["company_number"]
            if num in PILOT:
                continue
            first = (chk.get("gazette_first_trouble") or {}).get("date") or c["exposed_on"]
            as_of = bp.days(first, -90)
            prof = ch.company(num) or {}
            ceased = prof.get("date_of_cessation")
            if ceased and ceased <= as_of:
                as_of = bp.days(ceased, -90)
            if as_of < bp.days(prof.get("date_of_creation", "9999-01-01"), 60):
                continue
            out.append({"number": num, "as_of": as_of,
                        "label": {"decision": "bad", "issues": [], "slice": "real", "channel": "scam_wound_up",
                                  "set": "historical", "verdict": c["verdict"], "exposed_on": first,
                                  "source": c["source_url"]}})
    return out


def review_cases():
    rows = [json.loads(l) for l in open("data/labels/raw/rp05_dates.jsonl")]
    pool = [r for r in rows if r["rp05"] and "2025-01-01" <= r["rp05"] < WINDOW_FROM and r.get("incorporated")
            and r["company_number"] not in PILOT]
    out = []
    for r in rng.sample(pool, len(pool)):
        as_of = bp.days(r["rp05"], -90)
        if as_of < bp.days(r["incorporated"], 60):
            continue
        out.append({"number": r["company_number"], "as_of": as_of,
                    "label": {"decision": "review", "issues": [], "slice": "real", "channel": "registrar_action",
                              "set": "historical", "exposed_on": r["rp05"]}})
        if len(out) == N["review"]:
            break
    return out


def matched_clean(targets, n, exclude, sic=None):
    """Ordinary active companies, each matched to a random target case by incorporation date (±45
    days) and given that case's as_of (±30 days)."""
    out, tries = [], 0
    while len(out) < n and tries < n * 25:
        tries += 1
        t = rng.choice(targets)
        inc = dt.date.fromisoformat(t["incorporated"])
        params = {"company_status": "active", "size": 100,
                  "incorporated_from": (inc - dt.timedelta(days=45)).isoformat(),
                  "incorporated_to": (inc + dt.timedelta(days=45)).isoformat()}
        if sic:
            params["sic_codes"] = sic
        items = [i for i in (ch._get("/advanced-search/companies", params) or {}).get("items", [])
                 if i["company_number"] not in exclude and i.get("company_type") in ("ltd", "plc", "llp")
                 and registrar.DEFAULT_POSTCODE not in str(i.get("registered_office_address", {}))]
        if not items:
            continue
        c = rng.choice(items)
        num = c["company_number"]
        if registrar.default_address_applied(num) or gazette.earliest_trouble(num):
            continue
        as_of = bp.days(t["as_of"], rng.randint(-30, 30))
        if as_of < bp.days(c["date_of_creation"], 90) or as_of >= WINDOW_FROM:
            continue
        out.append((c, as_of))
        exclude = set(exclude) | {num}
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    entries = bad_cases(); print("bad", len(entries), flush=True)
    entries += review_cases(); print("+review", len(entries), flush=True)
    bp.N["pep"] = N["pep"]
    entries += [e for e in bp.pep_cases() if e["number"] not in PILOT]; print("+pep", len(entries), flush=True)
    targets = []
    for e in entries:
        prof = ch.company(e["number"]) or {}
        if prof.get("date_of_creation"):
            targets.append({"incorporated": prof["date_of_creation"], "as_of": e["as_of"]})
    taken = {e["number"] for e in entries} | PILOT
    sics = list(bp.HIGH_RISK_SIC)
    for i in range(N["industry"]):
        for c, as_of in matched_clean(targets, 1, taken, sic=sics[i % len(sics)]):
            taken.add(c["company_number"])
            entries.append({"number": c["company_number"], "as_of": as_of,
                            "label": {"decision": "review", "issues": [], "slice": "real", "channel": "industry",
                                      "set": "historical", "industry": bp.HIGH_RISK_SIC[sics[i % len(sics)]],
                                      "pending": "industry and licence labels"}})
    print("+industry", len(entries), flush=True)
    for c, as_of in matched_clean(targets, N["clean"] + N["planted"], taken):
        taken.add(c["company_number"])
        entries.append({"number": c["company_number"], "as_of": as_of,
                        "label": {"decision": "good", "issues": [], "slice": "real", "channel": "none", "set": "historical"}})
    print("+clean", len(entries), flush=True)

    cases = []
    for e in entries:
        try:
            case = bp.build(e)
        except Exception as err:
            print(f"skip {e['number']}: {err}", flush=True)
            continue
        # An address that cannot be rebuilt for the case date is missing almost only for companies the
        # registrar later rejected, so its absence would give the label away: drop such cases everywhere.
        if case["registry"]["registered_address"] is None:
            print(f"skip {e['number']}: registered address at as_of unknown", flush=True)
            continue
        cases.append((case, e["label"]))
    pool = {
        "names": sorted({d["name"] for c, l in cases if l["channel"] == "none" for d in c["application"]["directors"]}),
        "disqualified": sorted({bp.person(d["title"]) for s in ("Smith", "Khan", "Patel", "Jones", "Ali", "Brown", "Taylor", "Ahmed")
                                for d in ch.search_disqualified(s)[:20] if d.get("title")}),
        "sanctioned": [e["name"] for e in bp.screening.sanctions_entries()
                       if e["list"] == "UK Sanctions List" and (e["type"] or "").lower() == "individual"][400:800],
        "sites": [], "industries": ["47910", "64999", "92000", "66190", "46900", "56101", "68100", "62020"],
    }
    clean_idx = [i for i, (c, l) in enumerate(cases) if l["channel"] == "none"]
    for i in rng.sample(clean_idx, min(N["planted"], len(clean_idx))):
        c, _ = cases[i]
        planted_case, lab = plant(c, rng.sample(bp.PLANTABLE, rng.choice([1, 1, 2])), pool, nrng)
        lab.update({"channel": "planted", "set": "historical"})
        cases[i] = (planted_case, lab)

    rng.shuffle(cases)
    labels = {}
    with open(OUT / "cases.jsonl", "w") as f:
        for n, (c, l) in enumerate(cases, 1):
            c["case_id"] = f"val-{n:03d}"
            bp.screen(c)
            labels[c["case_id"]] = bp.confirm(c, {**l, "company_number": c["registry"]["company_number"]})
            f.write(json.dumps(c) + "\n")
            if n % 25 == 0:
                print("screened", n, flush=True)
    json.dump(labels, open(OUT / "labels.json", "w"), indent=1)
    summary = {}
    for l in labels.values():
        summary[f"{l['channel']}/{l['decision']}"] = summary.get(f"{l['channel']}/{l['decision']}", 0) + 1
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
