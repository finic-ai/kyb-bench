"""Tuned track: decision thresholds fitted on the validation split, applied unchanged to the pilot.

For each system run on both splits: choose the (lower, upper) thresholds on its score that
minimise expected cost on validation (SPEC.md 5.1), turn its pilot scores into decisions with
them, and compare with its out-of-the-box decisions. Only decision-scored cases are used.

    .venv/bin/python scripts/tune.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kybbench import cost_matrix, scoring  # noqa: E402
from run_pilot import decision_scored  # noqa: E402

DECISIONS = ("approve", "review", "decline")
# Label mix the test sets are built at (SPEC.md 4.3); an assumption until the cost matrix is set.
TARGET_MIX = {"good": 0.90, "review": 0.07, "bad": 0.03}


def load(split, run):
    labels = json.load(open(f"data/{split}/labels.json"))
    preds = {p["case_id"]: p for p in map(json.loads, open(f"runs/{split}/{run}/predictions.jsonl"))}
    ids = [i for i in sorted(labels) if decision_scored(labels[i]) and i in preds]
    return [labels[i]["decision"] for i in ids], np.array([preds[i]["score"] for i in ids]), [preds[i]["decision"] for i in ids]


def summary(truth, decisions):
    costs = cost_matrix()
    w = scoring.prevalence_weights(truth, TARGET_MIX)
    want = {"good": "approve", "review": "review", "bad": "decline"}
    bad = [d for t, d in zip(truth, decisions) if t == "bad"]
    good = [d for t, d in zip(truth, decisions) if t == "good"]
    return {
        "accuracy": round(np.mean([want[t] == d for t, d in zip(truth, decisions)]), 3),
        "cost_per_app_as_sampled": round(float(np.mean([costs[d][t] for t, d in zip(truth, decisions)])), 1),
        "cost_per_app_at_target_mix": round(float(np.average([costs[d][t] for t, d in zip(truth, decisions)], weights=w)), 1),
        "bad_declined": round(np.mean([d == "decline" for d in bad]), 3),
        "bad_not_approved": round(np.mean([d != "approve" for d in bad]), 3),
        "good_wrongly_stopped": round(np.mean([d != "approve" for d in good]), 3),
    }


def main():
    rows = {}
    for run in sorted(p.name for p in Path("runs/validation").iterdir() if (p / "predictions.jsonl").exists()):
        if not (Path("runs/pilot") / run / "predictions.jsonl").exists():
            continue
        vt, vs, _ = load("validation", run)
        thresholds = scoring.choose_thresholds(vs, vt, weights=scoring.prevalence_weights(vt, TARGET_MIX))
        pt, ps, native = load("pilot", run)
        tuned = [DECISIONS[i] for i in scoring.decide(ps, thresholds)]
        rows[run] = {"thresholds": [round(t, 3) for t in thresholds], "n_validation": len(vt), "n_pilot": len(pt),
                     "out_of_the_box": summary(pt, native), "tuned": summary(pt, tuned)}
    Path("runs/tuned.json").write_text(json.dumps(rows, indent=1))
    for run, r in rows.items():
        print(f"\n{run}  thresholds {r['thresholds']} (fitted on {r['n_validation']} validation cases, reweighted to {TARGET_MIX})")
        for k in ("out_of_the_box", "tuned"):
            print(f"  {k:15} {r[k]}")


if __name__ == "__main__":
    main()
