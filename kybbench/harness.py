"""Runs a system over cases and records a trace per case (SPEC.md section 7).

A system is any function `predict(case) -> prediction`. Inside it, the system records what it
spent with the span helpers, which attach to the case currently being run:

    from kybbench import harness

    def predict(case):
        resp = client.messages.create(...)
        harness.llm_call(model, resp.usage.input_tokens, resp.usage.output_tokens, latency_ms)
        return {"case_id": case["case_id"], "score": ...}
"""

import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import uuid
from pathlib import Path

from kybbench import load_json
from kybbench.schema import check_prediction

_spans = contextvars.ContextVar("spans", default=None)


def _record(span):
    spans = _spans.get()
    if spans is None:
        raise RuntimeError("span recorded outside harness.run")
    spans.append(span)


def llm_call(model, input_tokens, output_tokens, latency_ms):
    _record({"type": "llm_call", "model": model, "input_tokens": int(input_tokens),
             "output_tokens": int(output_tokens), "latency_ms": int(latency_ms)})


def model_infer(model, latency_ms):
    _record({"type": "model_infer", "model": model, "latency_ms": int(latency_ms)})


def tool_call(tool, args, latency_ms):
    _record({"type": "tool_call", "tool": tool, "args": args, "latency_ms": int(latency_ms)})


def _totals(spans, wall_ms):
    llm = [s for s in spans if s["type"] == "llm_call"]
    return {
        "wall_ms": wall_ms,
        "calls": sum(s["type"] in ("llm_call", "model_infer") for s in spans),
        "tool_calls": sum(s["type"] == "tool_call" for s in spans),
        "input_tokens": sum(s["input_tokens"] for s in llm),
        "output_tokens": sum(s["output_tokens"] for s in llm),
    }


def run(predict, cases, system, out_dir, workers=1):
    """Write predictions.jsonl and traces.jsonl to out_dir, resuming if they already exist.

    system: {"name", "version", "type", "mode"} as in the trace format. With workers > 1, cases run
    concurrently; each case records its spans in its own context.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pred_path, trace_path = out / "predictions.jsonl", out / "traces.jsonl"
    done = set()
    if pred_path.exists():
        done = {json.loads(l)["case_id"] for l in pred_path.read_text().splitlines() if l.strip()}
    run_id = uuid.uuid4().hex
    lock = threading.Lock()
    todo = [c for c in cases if c["case_id"] not in done]

    def one(case):
        spans = []
        _spans.set(spans)
        start = time.monotonic()
        pred = predict(case)
        wall_ms = int((time.monotonic() - start) * 1000)
        problems = check_prediction(pred)
        if problems or pred["case_id"] != case["case_id"]:
            raise ValueError(f"bad prediction for {case['case_id']}: {problems or 'case_id mismatch'}")
        trace = {"case_id": case["case_id"], "run_id": run_id, "system": system,
                 "spans": spans, "totals": _totals(spans, wall_ms)}
        with lock:
            with pred_path.open("a") as f:
                f.write(json.dumps(pred) + "\n")
            with trace_path.open("a") as f:
                f.write(json.dumps(trace) + "\n")

    with ThreadPoolExecutor(max(1, workers)) as ex:
        futures = [ex.submit(contextvars.copy_context().run, one, c) for c in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if n % 50 == 0:
                print(f"{system['name']}: {n}/{len(todo)} cases", flush=True)
    return pred_path, trace_path


def cost_usd(trace, prices):
    """Cost of one case from its trace and a price table (prices/YYYY-MM.json)."""
    total = 0.0
    for s in trace["spans"]:
        p = prices["models"].get(s.get("model"), {})
        if s["type"] == "llm_call" and "input_per_mtok_usd" in p:
            total += (s["input_tokens"] * p["input_per_mtok_usd"] + s["output_tokens"] * p["output_per_mtok_usd"]) / 1e6
        elif s["type"] == "llm_call":
            total += p.get("per_call_usd", 0.0)
        elif s["type"] == "model_infer":
            total += p.get("per_call_usd", 0.0)
        elif s["type"] == "tool_call":
            total += prices.get("per_tool_call_usd", 0.0)
    return total


def load_prices(month):
    return load_json(f"prices/{month}.json")
