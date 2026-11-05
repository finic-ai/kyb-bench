"""Build the `shutdowns` split: historical public-interest winding-up companies (The Gazette) not
used in the pilot or validation, labelled bad, plus ordinary companies matched to them by age and
case date (one per shutdown), so results with and without this channel can be compared.

    set -a; . ./.env; set +a; .venv/bin/python scripts/build_shutdowns.py
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pilot as bp  # noqa: E402
import build_validation as bv  # noqa: E402
from kybbench import companies_house as ch  # noqa: E402

OUT = Path("data/shutdowns")
rng = random.Random(23)
bp.rng = bv.rng = rng


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    used = {json.loads(l)["registry"]["company_number"] for f in ("data/pilot/cases.jsonl", "data/validation/cases.jsonl")
            for l in open(f)}
    entries = []
    for c in json.load(open("data/labels/candidates_public_interest.json"))["candidates"]:
        if c["set"] != "historical" or c["company_number"] in used:
            continue
        prof = ch.company(c["company_number"]) or {}
        as_of = bp.days(c["exposed_on"], -90)
        if prof.get("date_of_cessation") and prof["date_of_cessation"] <= as_of:
            as_of = bp.days(prof["date_of_cessation"], -90)
        if not prof.get("date_of_creation") or as_of < bp.days(prof["date_of_creation"], 60):
            continue
        entries.append({"number": c["company_number"], "as_of": as_of, "incorporated": prof["date_of_creation"],
                        "label": {"decision": "bad", "issues": [], "slice": "real", "channel": "public_interest_wound_up",
                                  "set": "historical", "exposed_on": c["exposed_on"], "source": c["source_url"]}})
    print("shutdowns", len(entries), flush=True)
    targets = [{"incorporated": e["incorporated"], "as_of": e["as_of"]} for e in entries]
    taken = used | {e["number"] for e in entries}
    for c, as_of in bv.matched_clean(targets, len(entries), taken):
        entries.append({"number": c["company_number"], "as_of": as_of,
                        "label": {"decision": "good", "issues": [], "slice": "real", "channel": "none", "set": "historical"}})
    print("+matched ordinary", len(entries), flush=True)

    labels, n = {}, 0
    with open(OUT / "cases.jsonl", "w") as f:
        for e in entries:
            try:
                case = bp.build(e)
            except Exception as err:
                print(f"skip {e['number']}: {err}", flush=True)
                continue
            if case["registry"]["registered_address"] is None:  # see build_validation: absence would leak the label
                print(f"skip {e['number']}: registered address at as_of unknown", flush=True)
                continue
            n += 1
            case["case_id"] = f"shut-{n:03d}"
            bp.screen(case)
            labels[case["case_id"]] = bp.confirm(case, {**e["label"], "company_number": e["number"]})
            f.write(json.dumps(case) + "\n")
    json.dump(labels, open(OUT / "labels.json", "w"), indent=1)
    summary = {}
    for l in labels.values():
        summary[f"{l['channel']}/{l['decision']}"] = summary.get(f"{l['channel']}/{l['decision']}", 0) + 1
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
