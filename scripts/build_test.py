"""Build a test split (SPEC.md 4.3): `fresh` (labels exposed on or after the window start) or
`historical`. Real-outcome bad cases at about 3%, the rest age-matched ordinary companies (some
with planted issues), plus address-rejected, PEP and high-risk-industry companies. No company from
the pilot, validation or the other test split is reused. Test labels are written next to the
cases but are git-ignored: they must never be published.

    set -a; . ./.env; set +a; .venv/bin/python scripts/build_test.py fresh
    set -a; . ./.env; set +a; .venv/bin/python scripts/build_test.py historical
"""

import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pilot as bp  # noqa: E402
import build_validation as bv  # noqa: E402
from kybbench import companies_house as ch  # noqa: E402
from kybbench.plant import plant  # noqa: E402

WINDOW_FROM = "2026-08-03"
PLAN = {
    "fresh": {"review": 30, "pep": 10, "industry": 20, "clean": 180, "planted": 100, "seed": 31},
    "historical": {"review": 100, "pep": 30, "industry": 60, "clean": 1150, "planted": 450, "seed": 37},
}


def used_numbers(exclude_split):
    out = set()
    for d in ("pilot", "validation", "shutdowns", "test_fresh", "test_historical"):
        f = Path(f"data/{d}/cases.jsonl")
        if f.exists() and d != exclude_split:
            out |= {json.loads(l)["registry"]["company_number"] for l in open(f)}
    return out


def bad_entries(kind, used):
    out = []
    for c in json.load(open("data/labels/candidates_public_interest.json"))["candidates"]:
        if c["set"] != kind or c["company_number"] in used:
            continue
        prof = ch.company(c["company_number"]) or {}
        as_of = bp.days(c["exposed_on"], -90)
        if prof.get("date_of_cessation") and prof["date_of_cessation"] <= as_of:
            as_of = bp.days(prof["date_of_cessation"], -90)
        if not prof.get("date_of_creation") or as_of < bp.days(prof["date_of_creation"], 60):
            continue
        out.append({"number": c["company_number"], "as_of": as_of,
                    "label": {"decision": "bad", "issues": [], "slice": "real", "channel": "public_interest_wound_up",
                              "set": kind, "exposed_on": c["exposed_on"], "source": c["source_url"]}})
    return out


def review_entries(kind, n, used, rng):
    rows = [json.loads(l) for l in open("data/labels/raw/rp05_dates.jsonl")]
    fresh = kind == "fresh"
    pool = [r for r in rows if r["rp05"] and r.get("incorporated") and r["company_number"] not in used
            and ((r["rp05"] >= WINDOW_FROM) if fresh else ("2025-01-01" <= r["rp05"] < WINDOW_FROM))]
    out = []
    for r in rng.sample(pool, len(pool)):
        as_of = bp.days(r["rp05"], -90)
        if as_of < bp.days(r["incorporated"], 60):
            continue
        out.append({"number": r["company_number"], "as_of": as_of,
                    "label": {"decision": "review", "issues": [], "slice": "real", "channel": "registrar_action",
                              "set": kind, "exposed_on": r["rp05"]}})
        if len(out) == n:
            break
    return out


def plant_into(cases, clean_idx, n, kind, rng, nrng):
    """Plant issues into n of the clean cases at clean_idx, in place: [(case, label), ...]."""
    pool = {
        "names": sorted({d["name"] for c, l in cases if l["channel"] == "none" for d in c["application"]["directors"]}),
        "disqualified": sorted({bp.person(d["title"]) for s in ("Smith", "Khan", "Patel", "Jones", "Ali", "Brown", "Taylor", "Ahmed", "Hussain", "Evans")
                                for d in ch.search_disqualified(s)[:20] if d.get("title")}),
        "sanctioned": [e["name"] for e in bp.screening.sanctions_entries()
                       if e["list"] == "UK Sanctions List" and (e["type"] or "").lower() == "individual"][800:1600],
        "sites": [], "industries": ["47910", "64999", "92000", "66190", "46900", "56101", "68100", "62020"],
    }
    chosen = rng.sample(clean_idx, min(n, len(clean_idx)))
    for i in chosen:
        c, _ = cases[i]
        planted_case, lab = plant(c, rng.sample(bp.PLANTABLE, rng.choice([1, 1, 2])), pool, nrng)
        lab.update({"channel": "planted", "set": kind})
        cases[i] = (planted_case, lab)
    return chosen


def replant(kind):
    """Plant issues into an already built split (fixes builds that planted nothing), keeping case
    ids, order and web evidence. Planted cases are re-screened and their labels re-confirmed."""
    plan = PLAN[kind]
    d = Path(f"data/test_{kind}")
    rows = [json.loads(l) for l in open(d / "cases.jsonl")]
    labels = json.load(open(d / "labels.json"))
    assert not any(l["channel"] == "planted" for l in labels.values()), "split already has planted cases"
    rng, nrng = random.Random(plan["seed"] + 1), np.random.default_rng(plan["seed"] + 1)
    cases = [(c, labels[c["case_id"]]) for c in rows]
    shutdown_ids = set()
    if kind == "historical":
        shutdown_ids = {json.loads(l)["registry"]["company_number"] for l in open("data/shutdowns/cases.jsonl")}
    clean_idx = [i for i, (c, l) in enumerate(cases) if l["channel"] == "none" and l["decision"] == "good"
                 and c["registry"]["company_number"] not in shutdown_ids]
    for n, i in enumerate(plant_into(cases, clean_idx, plan["planted"], kind, rng, nrng), 1):
        c, l = cases[i]
        c["case_id"] = rows[i]["case_id"]
        bp.screen(c)
        labels[c["case_id"]] = bp.confirm(c, {**l, "company_number": c["registry"]["company_number"]})
        rows[i] = c
        if n % 50 == 0:
            print("replanted", n, flush=True)
    with open(d / "cases.jsonl", "w") as f:
        f.writelines(json.dumps(c) + "\n" for c in rows)
    json.dump(labels, open(d / "labels.json", "w"), indent=1)
    print({k: sum(l["channel"] == k for l in labels.values()) for k in sorted({l["channel"] for l in labels.values()})})


def main():
    if sys.argv[1] == "replant":
        return replant(sys.argv[2])
    kind = sys.argv[1]
    plan = PLAN[kind]
    out_dir = Path(f"data/test_{kind}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(plan["seed"])
    nrng = np.random.default_rng(plan["seed"])
    bp.rng = bv.rng = rng
    used = used_numbers(f"test_{kind}")

    if kind == "historical":  # the shutdowns split was never used for tuning: it becomes the core
        entries = [{"case": c, "label": l} for c, l in zip(map(json.loads, open("data/shutdowns/cases.jsonl")),
                                                             json.load(open("data/shutdowns/labels.json")).values())]
        used -= {e["case"]["registry"]["company_number"] for e in entries}
        new = []
    else:
        entries, new = [], bad_entries(kind, used)
    print("bad (new)", len(new), "| carried over", len(entries), flush=True)
    new += review_entries(kind, plan["review"], used, rng)
    print("+review", len(new), flush=True)
    bp.N["pep"] = plan["pep"]
    if kind == "fresh":
        new += [e for e in bp.pep_cases() if e["number"] not in used]
    else:  # historical PEP cases: same sampling, case dates moved before the window
        for e in bp.pep_cases():
            if e["number"] not in used:
                e["as_of"] = bp.days(e["as_of"], -rng.randint(120, 400))
                e["label"]["set"] = "historical"
                new.append(e)
    print("+pep", len(new), flush=True)

    targets = []
    for e in new:
        prof = ch.company(e["number"]) or {}
        if prof.get("date_of_creation"):
            targets.append({"incorporated": prof["date_of_creation"], "as_of": e["as_of"]})
    targets += [{"incorporated": e["case"]["registry"]["incorporated"], "as_of": e["case"]["as_of"]} for e in entries]
    taken = used | {e["number"] for e in new}
    window_ok = (lambda a: a < WINDOW_FROM) if kind == "historical" else (lambda a: True)
    sics = list(bp.HIGH_RISK_SIC)
    for i in range(plan["industry"]):
        for c, as_of in bv.matched_clean(targets, 1, taken, sic=sics[i % len(sics)]):
            if window_ok(as_of):
                taken.add(c["company_number"])
                new.append({"number": c["company_number"], "as_of": as_of,
                            "label": {"decision": "review", "issues": [], "slice": "real", "channel": "industry",
                                      "set": kind, "industry": bp.HIGH_RISK_SIC[sics[i % len(sics)]],
                                      "pending": "industry and licence labels"}})
    print("+industry", len(new), flush=True)
    for c, as_of in bv.matched_clean(targets, plan["clean"] + plan["planted"], taken):
        if window_ok(as_of):
            taken.add(c["company_number"])
            new.append({"number": c["company_number"], "as_of": as_of,
                        "label": {"decision": "good", "issues": [], "slice": "real", "channel": "none", "set": kind}})
    print("+clean", len(new), flush=True)

    cases = [(e["case"], e["label"]) for e in entries]
    for e in new:
        try:
            case = bp.build(e)
        except Exception as err:
            print(f"skip {e['number']}: {err}", flush=True)
            continue
        if case["registry"]["registered_address"] is None:  # absence would leak the label (see build_validation)
            continue
        cases.append((case, e["label"]))

    n_carried = len(entries)  # carried-over shutdowns cases are never planted
    plant_into(cases, [i for i, (c, l) in enumerate(cases) if l["channel"] == "none" and i >= n_carried],
               plan["planted"], kind, rng, nrng)

    rng.shuffle(cases)
    labels = {}
    prefix = "tf" if kind == "fresh" else "th"
    with open(out_dir / "cases.jsonl", "w") as f:
        for n, (c, l) in enumerate(cases, 1):
            c = dict(c)
            c["case_id"] = f"{prefix}-{n:04d}"
            if "screening" not in c:
                bp.screen(c)
            labels[c["case_id"]] = bp.confirm(c, {**l, "company_number": c["registry"]["company_number"]})
            f.write(json.dumps(c) + "\n")
            if n % 100 == 0:
                print("screened", n, flush=True)
    json.dump(labels, open(out_dir / "labels.json", "w"), indent=1)
    summary = {}
    for l in labels.values():
        summary[f"{l['channel']}/{l['decision']}"] = summary.get(f"{l['channel']}/{l['decision']}", 0) + 1
    real = [l for l in labels.values() if l["channel"] != "planted"]
    print(json.dumps(summary, indent=1), "| real-outcome bad share:", round(sum(l["decision"] == "bad" for l in real) / len(real), 3))


if __name__ == "__main__":
    main()
