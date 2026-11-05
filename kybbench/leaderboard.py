"""Submission scoring shared by `kybbench eval` and the hidden-label scoring service (kybbench/server.py).

Only aggregate metrics are returned, never per-case results, so test labels cannot be recovered
by probing. Labels travel in a compact form: {case_id: {"d": decision, "c": channel, "i": issues,
"p": pending}}.
"""

import base64
import gzip
import json

import numpy as np

from kybbench import scoring

WANT = {"good": "approve", "review": "review", "bad": "decline"}
DECISIONS = set(WANT.values())
FUTURE_RISK = {"registrar_action"}
MIN_SLICE = 10  # slices smaller than this are not reported, so few cases are ever singled out


def pack(labels):
    compact = {cid: {"d": l["decision"], "c": l["channel"], "i": l.get("issues", []), "p": bool(l.get("pending"))}
               for cid, l in labels.items()}
    return base64.b64encode(gzip.compress(json.dumps(compact, separators=(",", ":")).encode())).decode()


def unpack(blob):
    return json.loads(gzip.decompress(base64.b64decode(blob)))


def _clean(pred):
    """A malformed prediction counts as a failure, scored as review with a neutral score."""
    dec = pred.get("decision")
    try:
        sc = float(pred.get("score", 0.5))
    except (TypeError, ValueError):
        sc = None
    if dec not in DECISIONS or sc is None or not 0 <= sc <= 1:
        return {"decision": "review", "score": 0.5}
    return {"decision": dec, "score": sc}


def score(labels, preds):
    """labels: compact labels; preds: {case_id: prediction}. Returns aggregate metrics."""
    preds = {c: _clean(p) for c, p in preds.items() if c in labels}
    missing = sorted(set(labels) - set(preds))
    ids = [c for c in sorted(labels) if labels[c]["c"] not in FUTURE_RISK and not labels[c]["p"] and c in preds]
    truth = [labels[c]["d"] for c in ids]
    dec = np.array([preds[c]["decision"] for c in ids])
    sc = np.array([preds[c]["score"] for c in ids])
    t = np.array(truth)
    out = {
        "n_cases": len(labels), "n_missing": len(missing), "n_scored": len(ids),
        "accuracy": round(float(np.mean([WANT[x] == d for x, d in zip(truth, dec)])), 3),
        "pr_auc": round(scoring.average_precision(t == "bad", sc), 3),
        "bad_declined": round(float(np.mean(dec[t == "bad"] == "decline")), 3),
        "bad_not_approved": round(float(np.mean(dec[t == "bad"] != "approve")), 3),
        "good_wrongly_stopped": round(float(np.mean(dec[t == "good"] != "approve")), 3),
        "by_group": {},
    }
    for ch in sorted({labels[c]["c"] for c in ids}):
        sub = [i for i, c in enumerate(ids) if labels[c]["c"] == ch]
        if len(sub) >= MIN_SLICE:
            out["by_group"][ch] = {"n": len(sub), "accuracy": round(float(np.mean([WANT[truth[i]] == dec[i] for i in sub])), 3)}
    fut = [c for c in labels if labels[c]["c"] in FUTURE_RISK and c in preds]
    clean = [c for c in labels if labels[c]["c"] == "none" and c in preds]
    if len(fut) >= MIN_SLICE and clean:
        y = np.array([True] * len(fut) + [False] * len(clean))
        out["future_risk_roc_auc"] = round(scoring.roc_auc(y, np.array([preds[c]["score"] for c in fut + clean])), 3)
    return out
