"""Results table across validation and the test splits, with the same aggregate metrics the
scoring API returns (kybbench.leaderboard). Systems run on the full historical split are also
scored on the 600-case sample, so the models run only on the sample compare on equal cases.

    .venv/bin/python scripts/results_test.py            # writes runs/results_test.json and prints a table
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import leaderboard  # noqa: E402

SPLITS = ["test_fresh", "test_historical_s600", "test_historical", "validation"]
REAL_BAD = ("public_interest_wound_up", "scam_wound_up")


def name(run):
    return run.replace("llm-", "").replace("openrouter-", "").replace("-workflow", " workflow").replace("-agent", "")


def load(split):
    labels = json.load(open(f"data/{split}/labels.json"))
    runs = {}
    for src in ([split, "test_historical"] if split == "test_historical_s600" else [split]):
        for d in sorted(Path(f"runs/{src}").iterdir()) if Path(f"runs/{src}").exists() else []:
            p = d / "predictions.jsonl"
            if not d.is_dir() or not p.exists() or d.name in runs:
                continue
            preds = {x["case_id"]: x for x in map(json.loads, open(p)) if x["case_id"] in labels}
            if len(preds) == len(labels):
                fails = {json.loads(l)["case_id"] for l in open(d / "failures.jsonl")} if (d / "failures.jsonl").exists() else set()
                runs[d.name] = (preds, len(fails & set(labels)))
    return leaderboard.unpack(leaderboard.pack(labels)), runs


def main():
    out = {}
    for split in SPLITS:
        labels, runs = load(split)
        rows = []
        for run, (preds, fails) in runs.items():
            m = leaderboard.score(labels, preds)
            real = next((m["by_group"][g]["accuracy"] for g in REAL_BAD if g in m["by_group"]), None)
            rows.append({"system": name(run), "run": run, "failures": fails, "real_bad_declined": real, **m})
        rows.sort(key=lambda r: r["cost_per_application_usd"])
        out[split] = rows
        print(f"\n== {split} ({rows[0]['n_scored'] if rows else 0} scored)")
        print(f"{'system':44} {'loss':>6} {'acc':>5} {'prauc':>6} {'bad dec':>8} {'good stop':>10} {'real bad':>9} {'future':>7} {'fail':>5}")
        for r in rows:
            rb = f"{r['real_bad_declined']:.0%}" if r["real_bad_declined"] is not None else "-"
            fut = f"{r['future_risk_roc_auc']:.2f}" if "future_risk_roc_auc" in r else "-"
            print(f"{r['system']:44} ${r['cost_per_application_usd']:>5.0f} {r['accuracy']:>5.0%} {r['pr_auc']:>6.2f} "
                  f"{r['bad_declined']:>8.0%} {r['good_wrongly_stopped']:>10.0%} {rb:>9} {fut:>7} {r['failures']:>5}")
    Path("runs/results_test.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
