"""Grayson as the answerer in workflow mode (https://docs.finic.ai/reference/decide).

One decide call per case with every workflow question. The request uses `context` and reads
`probability`, as the Lending Club client does; the SageMaker README documents `state` and
`noul` instead, so both answer shapes are accepted.
"""

import os
import time

import requests

from kybbench import harness, workflow

URL = "https://api.finic.ai/v1/decide"
MODEL = "grayson-1"
_session = requests.Session()


def _body(case):
    qs = {}
    for key, q in workflow.questions().items():
        qs[key] = {"type": q["type"], "instructions": q["instructions"]}
        if q["type"] == "choice":
            qs[key]["criteria"] = q["criteria"]
    return {"model": MODEL, "context": case, "questions": qs}


def answer(case):
    start = time.monotonic()
    for attempt in range(6):
        r = _session.post(URL, json=_body(case), timeout=60, headers={
            "Authorization": f"Bearer {os.environ['GRAYSON_API_KEY']}", "Content-Type": "application/json"})
        if r.status_code == 200:
            break
        if r.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"Grayson {r.status_code} {r.headers.get('x-request-id')}: {r.text[:300]}")
        time.sleep(min(60, 2 ** attempt))
    else:
        raise RuntimeError("Grayson: gave up")
    harness.model_infer(MODEL, (time.monotonic() - start) * 1000)
    out = {}
    for key, a in r.json()["answers"].items():
        if "probabilities" in a and ("choice" in a or workflow.QUESTIONS[key]["type"] == "choice"):
            out[key] = {"choice": a.get("choice") or max(a["probabilities"], key=a["probabilities"].get),
                        "probabilities": a["probabilities"]}
        else:
            out[key] = a.get("noul", a.get("probability"))
    return out
