"""kybbench command line.

    kybbench run --cases cases.jsonl --system my_module:predict --name my-system --type llm --mode direct --out runs/x
    kybbench eval --labels labels.json --preds runs/x/predictions.jsonl [--val-labels ... --val-preds ...]
    kybbench check --cases cases.jsonl | --preds predictions.jsonl | --traces traces.jsonl
    kybbench download [--split validation ...] [--out data/]
    KYB_SUBMIT_KEY=... kybbench submit --split test_fresh --preds runs/x/predictions.jsonl --name my-system
"""

import argparse
import gzip
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import requests

from kybbench import harness, leaderboard, schema


def _jsonl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def _by_id(rows):
    return {r["case_id"]: r for r in rows}


def cmd_run(a):
    module, func = a.system.split(":")
    sys.path.insert(0, ".")
    predict = getattr(importlib.import_module(module), func)
    system = {"name": a.name, "version": a.version, "type": a.type, "mode": a.mode}
    preds, traces = harness.run(predict, _jsonl(a.cases), system, a.out)
    print(f"wrote {preds} and {traces}")


def cmd_eval(a):
    """Score predictions exactly as the test scoring service does (aggregate metrics)."""
    labels = leaderboard.unpack(leaderboard.pack(json.loads(Path(a.labels).read_text())))
    print(json.dumps(leaderboard.score(labels, _by_id(_jsonl(a.preds))), indent=2))


def cmd_check(a):
    jobs = [(a.cases, schema.check_case), (a.preds, schema.check_prediction), (a.traces, schema.check_trace)]
    bad = 0
    for path, check in jobs:
        if not path:
            continue
        for row in _jsonl(path):
            for p in check(row):
                bad += 1
                print(f"{path} {row.get('case_id')}: {p}")
    print("ok" if not bad else f"{bad} problems")
    sys.exit(1 if bad else 0)


SITE = os.environ.get("KYB_SITE", "https://www.kyb-bench.com")


def _fetch(path):
    r = requests.get(f"{SITE}/{path}", timeout=60)
    r.raise_for_status()
    return r.content


def cmd_download(a):
    manifest = json.loads(_fetch("data/manifest.json"))
    splits = manifest["splits"]
    if manifest.get("notice"):
        print(manifest["notice"], "\n")
    for split in a.split or sorted(splits):
        if split not in splits:
            sys.exit(f"unknown split {split}; available: {', '.join(sorted(splits))}")
        out = Path(a.out) / split
        out.mkdir(parents=True, exist_ok=True)
        for kind, target in (("cases", "cases.jsonl"), ("labels", "labels.json")):
            meta = splits[split].get(kind)
            if not meta:
                continue
            data = _fetch(f"data/{meta['file']}")
            if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                sys.exit(f"checksum mismatch for {meta['file']}")
            (out / target).write_bytes(gzip.decompress(data))
        print(f"{split}: {splits[split]['n_cases']} cases -> {out}" + ("" if "labels" in splits[split] else " (labels hidden)"))


def cmd_submit(a):
    key = os.environ.get("KYB_SUBMIT_KEY")
    if not key:
        sys.exit("set KYB_SUBMIT_KEY to your submitter key")
    # only the scored fields: raw answers and other extras would push large splits past the
    # server's request limit (4.5 MB)
    keep = ("case_id", "decision", "score", "industry", "risk_rating", "issues")
    preds = [{k: p[k] for k in keep if k in p} for p in _jsonl(a.preds)]
    system = {"name": a.name, "version": a.version, "type": a.type, "mode": a.mode}
    r = requests.post(f"{SITE}/api/score", json={"split": a.split, "system": system, "predictions": preds},
                      headers={"X-KYB-Key": key}, timeout=120)
    if not r.ok:
        sys.exit(f"{r.status_code}: {r.text}")
    print(json.dumps(r.json(), indent=2))


def main():
    p = argparse.ArgumentParser(prog="kybbench")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a system over cases, writing predictions and traces")
    r.add_argument("--cases", required=True)
    r.add_argument("--system", required=True, help="module:function taking a case, returning a prediction")
    r.add_argument("--name", required=True)
    r.add_argument("--version", default="")
    r.add_argument("--type", required=True, choices=schema.SYSTEM_TYPES)
    r.add_argument("--mode", required=True, choices=schema.MODES)
    r.add_argument("--out", required=True)
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("eval", help="score predictions against labels")
    e.add_argument("--labels", required=True, help="labels.json of a split with public labels")
    e.add_argument("--preds", required=True)
    e.set_defaults(fn=cmd_eval)

    c = sub.add_parser("check", help="validate case, prediction or trace files")
    c.add_argument("--cases")
    c.add_argument("--preds")
    c.add_argument("--traces")
    c.set_defaults(fn=cmd_check)

    d = sub.add_parser("download", help="download public case files (test splits come without labels)")
    d.add_argument("--split", action="append", help="split to fetch; repeatable; default all")
    d.add_argument("--out", default="data")
    d.set_defaults(fn=cmd_download)

    s = sub.add_parser("submit", help="score predictions on a hidden-label test split")
    s.add_argument("--split", required=True, choices=["test_fresh", "test_historical"])
    s.add_argument("--preds", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--version", default="")
    s.add_argument("--type", default="")
    s.add_argument("--mode", default="")
    s.set_defaults(fn=cmd_submit)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
