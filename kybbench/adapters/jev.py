"""Jev (TypeSafe) as the answerer in workflow mode (https://docs.typesafe.ai/api/system-one).

Same shape as the Grayson adapter: one call per case with every workflow question. Jev takes the
case as `state` and answers yes/no questions with `noul`.
"""

import os
import time

import requests

from kybbench import harness, workflow
from kybbench.adapters import grayson

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"
_session = requests.Session()


def answer(case):
    body = grayson._body(case)
    body["model"] = MODEL
    body["state"] = body.pop("context")
    start = time.monotonic()
    for attempt in range(6):
        r = _session.post(URL, json=body, timeout=120, headers={
            "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}", "Content-Type": "application/json"})
        if r.status_code == 200:
            break
        if r.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"Jev {r.status_code} {r.headers.get('x-request-id')}: {r.text[:300]}")
        time.sleep(min(60, 2 ** attempt))
    else:
        raise RuntimeError("Jev: gave up")
    harness.model_infer(MODEL, (time.monotonic() - start) * 1000)
    out = {}
    for key, a in r.json()["answers"].items():
        if "probabilities" in a and ("choice" in a or workflow.QUESTIONS[key]["type"] == "choice"):
            out[key] = {"choice": a.get("choice") or max(a["probabilities"], key=a["probabilities"].get),
                        "probabilities": a["probabilities"]}
        else:
            out[key] = a.get("noul", a.get("probability"))
    return out
