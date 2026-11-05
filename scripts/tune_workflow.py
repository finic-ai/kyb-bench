"""Tuned workflow track: fit each system's two policy cut-offs (decline-level and review-level
questions) on the validation split, then apply them unchanged to the pilot and shutdowns splits.

Uses the raw answers saved in workflow-mode predictions; no system is rerun. Cost is minimised at
the label mix in data/cost_matrix.json.

    .venv/bin/python scripts/tune_workflow.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kybbench import cost_matrix, load_json, scoring, workflow  # noqa: E402
from run_pilot import decision_scored  # noqa: E402

MIX = load_json("data/cost_matrix.json")["assumptions"]["label_mix_for_reported_cost"]
GRID = [round(x, 2) for x in np.arange(0.3, 0.96, 0.05)]
WANT = {"good": "approve", "review": "review", "bad": "decline"}


def load(split, run):
    p = Path(f"runs/{split}/{run}/predictions.jsonl")
    if not p.exists():
        return None
    labels = json.load(open(f"data/{split}/labels.json"))
    preds = {x["case_id"]: x for x in map(json.loads, open(p))}
    # a failed case has no answers; it is scored as review, as in the main report
    rows = [(labels[c]["decision"], preds[c].get("answers")) for c in sorted(labels)
            if decision_scored(labels[c]) and c in preds]
    complete = len(rows) == sum(decision_scored(l) for l in labels.values())
    return rows if complete and any(a for _, a in rows) else None


def evaluate(rows, decline_cut, review_cut):
    costs = cost_matrix()
    truth = [t for t, _ in rows]
    dec = np.array([workflow.decide("x", a, decline_cut, review_cut)["decision"] if a else "review" for _, a in rows])
    t = np.array(truth)
    w = scoring.prevalence_weights(truth, MIX)
    return {"cost": float(np.average([costs[d][x] for x, d in zip(truth, dec)], weights=w)),
            "acc": float(np.mean([WANT[x] == d for x, d in zip(truth, dec)])),
            "bad_declined": float(np.mean(dec[t == "bad"] == "decline")),
            "good_stopped": float(np.mean(dec[t == "good"] != "approve"))}


def main():
    runs = sorted(p.name for p in Path("runs/validation").iterdir() if "workflow" in p.name)
    out = {}
    for run in runs:
        val = load("validation", run)
        if val is None:
            continue
        best = min(((d, r) for d in GRID for r in GRID if r <= d), key=lambda c: evaluate(val, *c)["cost"])
        row = {"cuts": {"decline": best[0], "review": best[1]},
               "validation": {"default": evaluate(val, 0.5, 0.5), "tuned": evaluate(val, *best)}}
        for split in ("test_fresh", "test_historical"):
            rows = load(split, run)
            if rows:
                row[split] = {"default": evaluate(rows, 0.5, 0.5), "tuned": evaluate(rows, *best)}
        out[run] = row
    Path("runs/tuned_workflow.json").write_text(json.dumps(out, indent=1))
    for run, r in out.items():
        print(f"\n{run}  cut-offs decline {r['cuts']['decline']} / review {r['cuts']['review']}")
        for split in ("validation", "test_fresh", "test_historical"):
            if split in r:
                d, t = r[split]["default"], r[split]["tuned"]
                print(f"  {split:10} cost ${d['cost']:.0f} -> ${t['cost']:.0f} | acc {d['acc']:.0%} -> {t['acc']:.0%} "
                      f"| bad declined {d['bad_declined']:.0%} -> {t['bad_declined']:.0%} | good stopped {d['good_stopped']:.0%} -> {t['good_stopped']:.0%}")


if __name__ == "__main__":
    main()
