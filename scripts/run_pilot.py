"""Run one system in one mode over the pilot set and score it.

    .venv/bin/python scripts/run_pilot.py scorecard workflow
    .venv/bin/python scripts/run_pilot.py grayson workflow
    .venv/bin/python scripts/run_pilot.py llm prompt   --model anthropic:claude-opus-5-5
    .venv/bin/python scripts/run_pilot.py llm workflow --model openai:gpt-6-luna

Models are "provider:model" (kybbench/models.py). Agent mode runs in containers:
scripts/run_container.py.

Writes runs/pilot/<system>-<mode>[-model]/ with predictions.jsonl, traces.jsonl, failures.jsonl
and report.json. A case that fails (error or refusal) is scored as `review`, which is what an
analyst would do with a case the system could not assess, and counted in the report.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import cost_matrix, harness, issue_catalogue, scoring, workflow
from kybbench.schema import check_prediction  # noqa: E402

PILOT = Path(os.environ.get("KYB_SPLIT", "data/pilot"))  # which split to run on
RUNS = Path("runs") / PILOT.name
DECISION = {"good": "approve", "review": "review", "bad": "decline"}


def make_predict(system, mode, model):
    if system == "scorecard":
        from kybbench.baselines import scorecard
        return workflow.predict_with(scorecard.answer), {"type": "classical", "mode": "workflow", "model": "scorecard"}
    if system == "grayson":
        from kybbench.adapters import grayson
        return workflow.predict_with(grayson.answer), {"type": "decision_model", "mode": "workflow", "model": grayson.MODEL}
    if system == "jev":
        from kybbench.adapters import jev
        return workflow.predict_with(jev.answer), {"type": "decision_model", "mode": "workflow", "model": jev.MODEL}
    if system == "llm":
        if mode == "agent":
            raise SystemExit("agent mode runs in containers: scripts/run_container.py run --harness <name> --model <model>")
        from kybbench import llm
        fn = {"prompt": llm.prompt_mode, "workflow": lambda m: workflow.predict_with(llm.workflow_answer(m))}[mode](model)
        return fn, {"type": "llm", "mode": mode, "model": model}
    raise SystemExit(f"unknown system {system}")


def safe(predict, failures):
    codes = list(issue_catalogue())

    def run(case):
        try:
            pred = predict(case)
            problems = check_prediction(pred)
            if problems:  # malformed output (e.g. a probability outside 0-1) counts as the system's failure
                raise ValueError("malformed prediction: " + "; ".join(problems))
            return pred
        except Exception as e:
            failures.append({"case_id": case["case_id"], "error": f"{type(e).__name__}: {e}"[:500]})
            return {"case_id": case["case_id"], "score": 0.5, "decision": "review", "industry": "L_OTHER",
                    "risk_rating": "high", "issues": {c: 0.0 for c in codes}, "failed": True}
    return run


FUTURE_RISK = {"registrar_action"}  # outcome not derivable from the policy at the case date: ranking only


def decision_scored(label):
    return label["channel"] not in FUTURE_RISK and not label.get("pending")


def report(labels, preds, traces, prices, n_failed):
    all_ids = sorted(labels)
    ids = [i for i in all_ids if decision_scored(labels[i])]
    excluded = Counter("future-risk slice" if labels[i]["channel"] in FUTURE_RISK else "labels pending"
                       for i in all_ids if i not in ids)
    future = [i for i in all_ids if labels[i]["channel"] in FUTURE_RISK]
    clean = [i for i in all_ids if labels[i]["channel"] == "none"]
    costs = cost_matrix()
    truth = [labels[i]["decision"] for i in ids]
    dec = [preds[i]["decision"] for i in ids]
    conf = Counter(zip(truth, dec))
    exp_cost = float(np.mean([costs[d][t] for t, d in zip(truth, dec)]))
    bad = np.array([t == "bad" for t in truth])
    score = np.array([preds[i]["score"] for i in ids])
    planted = [i for i in ids if labels[i]["channel"] == "planted"]
    ind = [i for i in ids if labels[i].get("industry") and preds[i].get("industry")]
    by_channel = {}
    for ch in sorted({labels[i]["channel"] for i in ids}):
        sub = [i for i in ids if labels[i]["channel"] == ch]
        by_channel[ch] = round(np.mean([DECISION[labels[i]["decision"]] == preds[i]["decision"] for i in sub]), 3)
    # Claude Code reports its own cost, including prompt-cache pricing; prefer it when present
    usd = [traces[i]["totals"]["cost_usd"] if traces[i]["totals"].get("cost_usd") is not None
           else harness.cost_usd(traces[i], prices) for i in all_ids]
    tot = [traces[i]["totals"] for i in all_ids]
    fr = (future and clean and scoring.roc_auc(np.array([True] * len(future) + [False] * len(clean)),
                                              np.array([preds[i]["score"] for i in future + clean])))
    return {
        "n": len(all_ids), "n_decision_scored": len(ids), "excluded": dict(excluded), "failed": n_failed,
        "future_risk_roc_auc_vs_clean": round(fr, 3) if fr else None,
        "decision_accuracy": round(np.mean([DECISION[t] == d for t, d in zip(truth, dec)]), 3),
        # a cautious system reviews rather than declines; these separate catching from deciding
        "bad_declined": round(np.mean([d == "decline" for t, d in zip(truth, dec) if t == "bad"]), 3),
        "bad_not_approved": round(np.mean([d != "approve" for t, d in zip(truth, dec) if t == "bad"]), 3),
        "good_wrongly_stopped": round(np.mean([d != "approve" for t, d in zip(truth, dec) if t == "good"]), 3),
        "expected_cost_per_application_usd": round(exp_cost, 2),
        "reference_cost": {"approve_all": round(float(np.mean([costs["approve"][t] for t in truth])), 2),
                           "review_all": round(float(np.mean([costs["review"][t] for t in truth])), 2)},
        "confusion": {t: {d: conf[(t, d)] for d in ("approve", "review", "decline")} for t in ("good", "review", "bad")},
        "accuracy_by_channel": by_channel,
        "pr_auc_bad": round(scoring.average_precision(bad, score), 3),
        "roc_auc_bad": round(scoring.roc_auc(bad, score), 3),
        "planted_issue_macro_f1": round(scoring.issue_metrics([preds[i]["issues"] for i in planted],
                                                              [set(labels[i]["issues"]) for i in planted])["macro_f1"], 3) if planted else None,
        "industry_accuracy": round(np.mean([preds[i]["industry"] == labels[i]["industry"] for i in ind]), 3) if ind else None,
        "model_cost_per_case_usd": round(float(np.mean(usd)), 5),
        "median_seconds_per_case": round(float(np.median([t["wall_ms"] for t in tot])) / 1000, 2),
        "mean_calls_per_case": round(float(np.mean([t["calls"] for t in tot])), 2),
        "mean_tool_calls_per_case": round(float(np.mean([t["tool_calls"] for t in tot])), 2),
        "mean_tokens_per_case": round(float(np.mean([t["input_tokens"] + t["output_tokens"] for t in tot]))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system", choices=["scorecard", "grayson", "jev", "llm"])
    ap.add_argument("mode", choices=["workflow", "prompt", "agent"])
    ap.add_argument("--model", default="anthropic:claude-opus-5-5", help="provider:model")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=1, help="cases run concurrently")
    a = ap.parse_args()

    cases = [json.loads(l) for l in open(PILOT / "cases.jsonl")][: a.limit]
    labels = {k: v for k, v in json.load(open(PILOT / "labels.json")).items() if k in {c["case_id"] for c in cases}}
    predict, meta = make_predict(a.system, a.mode, a.model)
    name = f"{a.system}-{a.mode}" + (f"-{a.model.replace(':', '-').replace('/', '-')}" if a.system == "llm" else "")
    out = RUNS / name
    failures = []
    system = {"name": name, "version": meta["model"], "type": meta["type"], "mode": meta["mode"]}
    start = time.monotonic()
    harness.run(safe(predict, failures), cases, system, out, workers=a.workers)
    if failures:
        with open(out / "failures.jsonl", "a") as f:
            f.writelines(json.dumps(x) + "\n" for x in failures)
    preds = {p["case_id"]: p for p in map(json.loads, open(out / "predictions.jsonl"))}
    traces = {t["case_id"]: t for t in map(json.loads, open(out / "traces.jsonl"))}
    n_failed = sum(bool(p.get("failed")) for p in preds.values())
    rep = {"system": system, "run_seconds": round(time.monotonic() - start, 1),
           **report(labels, preds, traces, json.load(open("prices/2026-10.json")), n_failed)}
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
