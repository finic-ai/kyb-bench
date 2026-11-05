"""Rules scorecard harness: answers the workflow questions with hand-written rules (no model)."""

import json
import sys
import time

sys.path.insert(0, "/opt/kybbench")
from kybbench import workflow  # noqa: E402
from kybbench.baselines import scorecard  # noqa: E402

start = time.monotonic()
case = json.load(open("/case/case.json"))
with open("/out/prediction.json", "w") as f:
    json.dump(workflow.decide(case["case_id"], scorecard.answer(case)), f)
with open("/out/trace.json", "w") as f:
    json.dump({"model": "scorecard", "turns": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
               "duration_ms": int((time.monotonic() - start) * 1000)}, f)
