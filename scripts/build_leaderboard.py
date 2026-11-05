"""Build site/leaderboard.json from our own runs on the hidden test splits.

Out-of-the-box results only (default cut-offs), scored exactly as the scoring API scores a
submission (kybbench.leaderboard), ranked by PR-AUC with a 95% bootstrap interval, plus the model
cost per case priced from each run's traces. The fresh and historical splits are ranked together as
one test set; systems not run on every test case are listed but not ranked.

    .venv/bin/python scripts/build_leaderboard.py
"""

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import harness, leaderboard, scoring  # noqa: E402

PRICES = json.load(open("prices/2026-10.json"))
UNPRICED = {"grayson-1", "jev-1.14.0"}  # per-call prices not published
SPLITS = ("test_fresh", "test_historical")  # ranked together as one test set

SYSTEMS = {  # run directory -> (display name, organisation, type, mode)
    "grayson-workflow": ("Grayson", "Finic", "Decision model", "Workflow"),
    "jev-workflow": ("Jev", "TypeSafe", "Decision model", "Workflow"),
    "scorecard-workflow": ("Rules scorecard", "Baseline", "Rules", "Workflow"),
    "agent-claude-code-claude-haiku-5-5": ("Claude Code + Claude Haiku 5.5", "Anthropic", "LLM agent", "Agent"),
}
LLMS = {"anthropic-claude-sonnet-5.5": ("Claude Sonnet 5.5", "Anthropic"), "anthropic-claude-haiku-5.5": ("Claude Haiku 5.5", "Anthropic"),
        "openai-gpt-6.1-sol": ("GPT-6.1 Sol", "OpenAI"), "openai-gpt-6-luna": ("GPT-6 Luna", "OpenAI"),
        "google-gemini-3.8-flash": ("Gemini 3.8 Flash", "Google"), "deepseek-deepseek-v4.1-flash": ("DeepSeek V4.1 Flash", "DeepSeek"),
        "z-ai-glm-5.3": ("GLM-5.3", "Z.ai"), "qwen-qwen3.8-flash": ("Qwen3.8 Flash", "Alibaba")}
for mode in ("prompt", "workflow"):
    for key, (name, org) in LLMS.items():
        SYSTEMS[f"llm-{mode}-openrouter-{key}"] = (name, org, "LLM", mode.title())


def pr_auc_interval(labels, preds, n_boot=1000, seed=0):
    """95% bootstrap interval of PR-AUC, resampling scored cases."""
    ids = [c for c in sorted(labels) if labels[c]["c"] not in leaderboard.FUTURE_RISK and not labels[c]["p"] and c in preds]
    y = np.array([labels[c]["d"] == "bad" for c in ids])
    sc = np.array([leaderboard._clean(preds[c])["score"] for c in ids])
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n_boot):
        i = rng.integers(0, len(ids), len(ids))
        if y[i].any():
            stats.append(scoring.average_precision(y[i], sc[i]))
    return [round(float(np.percentile(stats, 2.5)), 3), round(float(np.percentile(stats, 97.5)), 3)]


def model_cost(run):
    traces = [json.loads(l) for split in SPLITS for l in open(f"runs/{split}/{run}/traces.jsonl")]
    models = {s.get("model") for t in traces for s in t["spans"]}
    if models & UNPRICED:
        return None
    return round(float(np.mean([harness.cost_usd(t, PRICES) for t in traces])), 5)


def main():
    labels, runs = {}, {}
    for split in SPLITS:
        raw = json.load(open(f"data/{split}/labels.json"))
        labels.update(leaderboard.unpack(leaderboard.pack(raw)))
    out = {"updated": dt.date.today().isoformat(),
           "note": "Labels are model-made and have not been audited by people.",
           "n_cases": len(labels), "test": [], "partial": []}
    for run, (name, org, typ, mode) in SYSTEMS.items():
        preds = {}
        for split in SPLITS:
            p = Path(f"runs/{split}/{run}/predictions.jsonl")
            if p.exists():
                preds.update({x["case_id"]: x for x in map(json.loads, open(p))})
        if len(set(preds) & set(labels)) < len(labels):
            out["partial"].append(f"{name} ({mode.lower()})")
            continue
        m = leaderboard.score(labels, preds)
        out["test"].append({
            "system": name, "org": org, "type": typ, "mode": mode,
            "pr_auc": m["pr_auc"], "pr_auc_ci": pr_auc_interval(labels, preds),
            "good_wrongly_stopped": m["good_wrongly_stopped"], "bad_declined": m["bad_declined"],
            "accuracy": m["accuracy"], "future_risk_roc_auc": m.get("future_risk_roc_auc"),
            "cost_per_decision_usd": model_cost(run), "n_scored": m["n_scored"], "verified": "reproduced", "date": "2026-11",
        })
    out["test"].sort(key=lambda r: -r["pr_auc"])
    Path("site/leaderboard.json").write_text(json.dumps(out, indent=1) + "\n")
    print(len(out["test"]), "ranked; not on the full test set:", out["partial"])


if __name__ == "__main__":
    main()
