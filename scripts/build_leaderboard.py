"""Build site/leaderboard.json from our own runs on the hidden test splits.

Out-of-the-box results only (default cut-offs), scored exactly as the scoring API scores a
submission (kybbench.leaderboard), ranked by PR-AUC with a 95% bootstrap interval, plus the model
cost per case priced from each run's traces. Systems run only on the 600-case historical sample
are not ranked on the historical tab, which uses the full split.

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
REAL_BAD = ("public_interest_wound_up", "scam_wound_up")
SPLITS = {"fresh": "test_fresh", "historical": "test_historical"}
# Jev was released on 2026-09-15 with no published training cutoff, after the fresh window opened
NOT_OUT_OF_SAMPLE = {("fresh", "jev-workflow"): "Released 15 Sep 2026, after the fresh window opened"}

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


def model_cost(run_dir):
    traces = [json.loads(l) for l in open(run_dir / "traces.jsonl")]
    models = {s.get("model") for t in traces for s in t["spans"]}
    if models & UNPRICED:
        return None
    return round(float(np.mean([harness.cost_usd(t, PRICES) for t in traces])), 5)


def main():
    out = {"updated": dt.date.today().isoformat(),
           "note": "Labels are model-made and have not been audited by people.",
           "fresh": [], "historical": [], "sample_only": []}
    for tab, split in SPLITS.items():
        raw = json.load(open(f"data/{split}/labels.json"))
        labels = leaderboard.unpack(leaderboard.pack(raw))
        for run, (name, org, typ, mode) in SYSTEMS.items():
            d = Path(f"runs/{split}/{run}")
            p = d / "predictions.jsonl"
            preds = {x["case_id"]: x for x in map(json.loads, open(p))} if p.exists() else {}
            if len(set(preds) & set(labels)) < len(labels):
                if tab == "historical" and Path(f"runs/test_historical_s600/{run}/predictions.jsonl").exists():
                    out["sample_only"].append(f"{name} ({mode.lower()})")
                continue
            m = leaderboard.score(labels, preds)
            real = next((m["by_group"][g]["accuracy"] for g in REAL_BAD if g in m["by_group"]), None)
            fails = sum(1 for _ in open(d / "failures.jsonl")) if (d / "failures.jsonl").exists() else 0
            out[tab].append({
                "system": name, "org": org, "type": typ, "mode": mode,
                "pr_auc": m["pr_auc"], "pr_auc_ci": pr_auc_interval(labels, preds), "accuracy": m["accuracy"], "bad_declined": m["bad_declined"],
                "good_wrongly_stopped": m["good_wrongly_stopped"], "real_bad_declined": real,
                "future_risk_roc_auc": m.get("future_risk_roc_auc"), "cost_per_decision_usd": model_cost(d),
                "failures": fails, "n_scored": m["n_scored"], "verified": "reproduced", "date": "2026-11",
                "flag": NOT_OUT_OF_SAMPLE.get((tab, run)),
            })
        out[tab].sort(key=lambda r: -r["pr_auc"])
        print(tab, len(out[tab]), "rows")
    Path("site/leaderboard.json").write_text(json.dumps(out, indent=1) + "\n")
    print("sample only on historical:", out["sample_only"])


if __name__ == "__main__":
    main()
