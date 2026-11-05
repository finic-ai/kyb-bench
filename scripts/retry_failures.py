"""Rerun cases that failed for infrastructure reasons (connection drops, timeouts, rate limits).

Model failures (empty or malformed output) are the system's own and stay scored as review.
Removes infrastructure-failed cases from a run's predictions, traces and failures, so the next
`run_pilot.py` with the same arguments (it resumes) runs them again.

    .venv/bin/python scripts/retry_failures.py runs/test_fresh/llm-prompt-openrouter-qwen-qwen3.8-flash ...
"""

import json
import sys
from pathlib import Path

INFRA = ("APIConnectionError", "APITimeoutError", "RateLimitError", "ConnectionError", "ReadTimeout",
         "InternalServerError", "ServiceUnavailable", "gave up")


def main():
    for run in map(Path, sys.argv[1:]):
        fpath = run / "failures.jsonl"
        if not fpath.exists():
            continue
        fails = [json.loads(l) for l in open(fpath)]
        retry = {f["case_id"] for f in fails if any(k in f["error"] for k in INFRA)}
        if not retry:
            continue
        for name in ("predictions.jsonl", "traces.jsonl"):
            p = run / name
            if p.exists():
                p.write_text("".join(l for l in open(p) if json.loads(l)["case_id"] not in retry))
        fpath.write_text("".join(json.dumps(f) + "\n" for f in fails if f["case_id"] not in retry))
        print(f"{run}: {len(retry)} to retry, {len(fails) - len(retry)} model failures kept")


if __name__ == "__main__":
    main()
