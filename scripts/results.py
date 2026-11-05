"""Pilot results: every system, out of the box and tuned (thresholds fitted on validation), with 95%
bootstrap intervals. Cost is reported at the label mix in data/cost_matrix.json.

    .venv/bin/python scripts/results.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kybbench import cost_matrix, load_json, scoring  # noqa: E402
from run_pilot import FUTURE_RISK, decision_scored  # noqa: E402

DECISIONS = ("approve", "review", "decline")
MIX = load_json("data/cost_matrix.json")["assumptions"]["label_mix_for_reported_cost"]
SYSTEMS = {"Rules scorecard (reference line)": "scorecard-workflow", "Grayson, workflow": "grayson-workflow",
           "Claude Code + Haiku 5.5, agent": "agent-claude-code-claude-haiku-5-5"}
WANT = {"good": "approve", "review": "review", "bad": "decline"}


def split_data(split, run):
    labels = json.load(open(f"data/{split}/labels.json"))
    preds = {p["case_id"]: p for p in map(json.loads, open(f"runs/{split}/{run}/predictions.jsonl"))}
    traces = {t["case_id"]: t for t in map(json.loads, open(f"runs/{split}/{run}/traces.jsonl"))}
    return labels, preds, traces


def metrics(truth, dec, score):
    costs = cost_matrix()
    truth, dec = np.array(truth), np.array(dec)
    w = scoring.prevalence_weights(list(truth), MIX)
    bad, good = truth == "bad", truth == "good"
    return {
        "accuracy": np.mean([WANT[t] == d for t, d in zip(truth, dec)]),
        "cost": np.average([costs[d][t] for t, d in zip(truth, dec)], weights=w),
        "bad_declined": np.mean(dec[bad] == "decline"),
        "bad_not_approved": np.mean(dec[bad] != "approve"),
        "good_wrongly_stopped": np.mean(dec[good] != "approve"),
        "pr_auc": scoring.average_precision(bad, score),
    }


def with_ci(truth, dec, score, n=1000, seed=0):
    point = metrics(truth, dec, score)
    rng = np.random.default_rng(seed)
    idx = np.arange(len(truth))
    samples = []
    for _ in range(n):
        i = rng.choice(idx, len(idx))
        if len({truth[j] for j in i}) < 3:
            continue
        samples.append(metrics([truth[j] for j in i], [dec[j] for j in i], score[i]))
    return {k: (point[k], *np.nanquantile([s[k] for s in samples], [0.025, 0.975])) for k in point}


def main():
    out = {}
    for name, run in SYSTEMS.items():
        vl, vp, _ = split_data("validation", run)
        vids = [i for i in sorted(vl) if decision_scored(vl[i])]
        vt = [vl[i]["decision"] for i in vids]
        thresholds = scoring.choose_thresholds(np.array([vp[i]["score"] for i in vids]), vt,
                                               weights=scoring.prevalence_weights(vt, MIX))
        pl, pp, ptr = split_data("pilot", run)
        ids = [i for i in sorted(pl) if decision_scored(pl[i])]
        truth = [pl[i]["decision"] for i in ids]
        score = np.array([pp[i]["score"] for i in ids])
        native = [pp[i]["decision"] for i in ids]
        tuned = [DECISIONS[k] for k in scoring.decide(score, thresholds)]
        future = [i for i in pl if pl[i]["channel"] in FUTURE_RISK]
        clean = [i for i in pl if pl[i]["channel"] == "none"]
        fr = scoring.roc_auc(np.array([True] * len(future) + [False] * len(clean)), np.array([pp[i]["score"] for i in future + clean]))
        cost_case = np.mean([ptr[i]["totals"].get("cost_usd") or 0.0 for i in pl])
        secs = np.median([ptr[i]["totals"]["wall_ms"] for i in pl]) / 1000
        out[name] = {"thresholds": [round(t, 3) for t in thresholds], "out_of_the_box": with_ci(truth, native, score),
                     "tuned": with_ci(truth, tuned, score), "future_risk_auc": fr, "model_cost_per_case": cost_case,
                     "seconds_per_case": secs, "n": len(ids)}
    review_all = metrics(truth, ["review"] * len(truth), np.zeros(len(truth)))["cost"]
    approve_all = metrics(truth, ["approve"] * len(truth), np.zeros(len(truth)))["cost"]
    Path("runs/pilot_results.json").write_text(json.dumps({"review_all_cost": review_all, "approve_all_cost": approve_all,
                                                           "systems": out}, indent=1, default=float))
    fmt = lambda m, k, pct: (f"{m[k][0]:.0%} [{m[k][1]:.0%}–{m[k][2]:.0%}]" if pct else f"${m[k][0]:.0f} [${m[k][1]:.0f}–${m[k][2]:.0f}]")
    print(f"Reference lines: review everything ${review_all:.0f}/app, approve everything ${approve_all:.0f}/app\n")
    for name, r in out.items():
        for mode in ("out_of_the_box", "tuned"):
            m = r[mode]
            print(f"{name} [{mode}] cost {fmt(m, 'cost', False)} | acc {fmt(m, 'accuracy', True)} | bad declined {fmt(m, 'bad_declined', True)} "
                  f"| bad not approved {fmt(m, 'bad_not_approved', True)} | good stopped {fmt(m, 'good_wrongly_stopped', True)} | PR-AUC {m['pr_auc'][0]:.2f}")
        print(f"   thresholds {r['thresholds']} | future-risk AUC {r['future_risk_auc']:.2f} | ${r['model_cost_per_case']:.4f}/case | {r['seconds_per_case']:.1f}s/case | n={r['n']}\n")


if __name__ == "__main__":
    main()
