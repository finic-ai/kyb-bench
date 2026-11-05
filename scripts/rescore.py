"""Rescore saved pilot runs against the current labels (no system is rerun).

    .venv/bin/python scripts/rescore.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pilot  # noqa: E402

labels = json.load(open(run_pilot.PILOT / "labels.json"))
prices = json.load(open("prices/2026-10.json"))
for d in sorted(run_pilot.RUNS.iterdir()):
    if not (d / "predictions.jsonl").exists():
        continue
    preds = {p["case_id"]: p for p in map(json.loads, open(d / "predictions.jsonl"))}
    traces = {t["case_id"]: t for t in map(json.loads, open(d / "traces.jsonl"))}
    old = json.load(open(d / "report.json")) if (d / "report.json").exists() else {}
    rep = {"system": old.get("system"), "run_seconds": old.get("run_seconds"),
           **run_pilot.report(labels, preds, traces, prices, sum(bool(p.get("failed")) for p in preds.values()))}
    (d / "report.json").write_text(json.dumps(rep, indent=1))
    print(d.name)
