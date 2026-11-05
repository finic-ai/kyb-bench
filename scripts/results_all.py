"""Leaderboard-style comparison of every system and mode that has run on the validation split,
with and without the public-interest shutdowns split counted in. Costs at the label mix in
data/cost_matrix.json.

    .venv/bin/python scripts/results_all.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kybbench import cost_matrix, harness, load_json, scoring  # noqa: E402
from run_pilot import decision_scored  # noqa: E402

MIX = load_json("data/cost_matrix.json")["assumptions"]["label_mix_for_reported_cost"]
PRICES = load_json("prices/2026-10.json")
WANT = {"good": "approve", "review": "review", "bad": "decline"}


def cases(split, run):
    p = Path(f"runs/{split}/{run}/predictions.jsonl")
    if not p.exists():
        return None
    labels = json.load(open(f"data/{split}/labels.json"))
    preds = {x["case_id"]: x for x in map(json.loads, open(p))}
    traces = {x["case_id"]: x for x in map(json.loads, open(f"runs/{split}/{run}/traces.jsonl"))}
    if len(preds) < len(labels):
        return None  # incomplete run
    rows = []
    for cid, lab in labels.items():
        if decision_scored(lab):
            t = traces[cid]["totals"]
            usd = t["cost_usd"] if t.get("cost_usd") is not None else harness.cost_usd(traces[cid], PRICES)
            rows.append((lab["decision"], lab["channel"], preds[cid]["decision"], preds[cid]["score"], usd,
                         bool(preds[cid].get("failed"))))
    return rows


def summarise(rows):
    costs = cost_matrix()
    truth = [r[0] for r in rows]
    dec = np.array([r[2] for r in rows])
    t = np.array(truth)
    w = scoring.prevalence_weights(truth, MIX)
    return {
        "n": len(rows),
        "cost": float(np.average([costs[d][x] for x, d in zip(truth, dec)], weights=w)),
        "acc": float(np.mean([WANT[x] == d for x, d in zip(truth, dec)])),
        "pr_auc": scoring.average_precision(t == "bad", np.array([r[3] for r in rows])),
        "bad_declined": float(np.mean(dec[t == "bad"] == "decline")),
        "bad_not_approved": float(np.mean(dec[t == "bad"] != "approve")),
        "good_stopped": float(np.mean(dec[t == "good"] != "approve")),
        "failed": sum(r[5] for r in rows),
    }


def main():
    runs = sorted(p.name for p in Path("runs/validation").iterdir() if (p / "predictions.jsonl").exists())
    table = []
    for run in runs:
        val, shut, pilot = cases("validation", run), cases("shutdowns", run), cases("pilot", run)
        if val is None:
            continue
        row = {"run": run, "without": summarise(val)}
        if shut is not None:
            row["with"] = summarise(val + shut)
            s = [r for r in shut if r[1] == "public_interest_wound_up"]
            row["shutdowns_declined"] = float(np.mean([r[2] == "decline" for r in s]))
            row["shutdowns_not_approved"] = float(np.mean([r[2] != "approve" for r in s]))
        if pilot is not None:
            row["pilot_acc"] = summarise(pilot)["acc"]
        mc = [r[4] for r in val if r[4] is not None]
        row["model_cost_per_case"] = float(np.mean(mc)) if mc else None
        table.append(row)
    table.sort(key=lambda r: r["without"]["cost"])
    Path("runs/results_all.json").write_text(json.dumps(table, indent=1))
    print(f"{'system / mode':58} {'val cost':>8} {'+shut cost':>10} {'val acc':>7} {'PR-AUC':>6} {'bad decl':>8} {'good stop':>9} "
          f"{'shut decl':>9} {'shut caught':>11} {'pilot acc':>9} {'$/case':>8}")
    for r in table:
        w, x = r["without"], r.get("with", {})
        print(f"{r['run']:58} ${w['cost']:>7.0f} {('$%.0f' % x['cost']) if x else '-':>10} {w['acc']:>7.0%} {w['pr_auc']:>6.2f} "
              f"{w['bad_declined']:>8.0%} {w['good_stopped']:>9.0%} {r.get('shutdowns_declined', float('nan')):>9.0%} "
              f"{r.get('shutdowns_not_approved', float('nan')):>11.0%} {r.get('pilot_acc', float('nan')):>9.0%} "
              f"{('$%.4f' % r['model_cost_per_case']) if r['model_cost_per_case'] is not None else '-':>8}")


if __name__ == "__main__":
    main()
