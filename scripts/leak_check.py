"""Leak check: can shallow case metadata (counts, dates, missing fields) tell a label group apart
from ordinary companies? Prints each feature's ROC-AUC for every real-outcome group against clean
cases, and a cross-validated logistic regression on all of them. Features far from 0.5 are either
real signal (judge by hand) or construction artefacts that must be fixed before release.

    .venv/bin/python scripts/leak_check.py data/test_fresh [data/validation ...]
"""

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_predict
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline


def days(a, b):
    try:
        return (dt.date.fromisoformat(a[:10]) - dt.date.fromisoformat(b[:10])).days
    except (TypeError, ValueError):
        return -1


def features(c):
    r, app = c["registry"], c["application"]
    filings = r.get("filings") or []
    last = max((f.get("date") or "" for f in filings), default="")
    web = c.get("web") or {}
    return {
        "age_days": days(c["as_of"], r.get("incorporated")),
        "as_of_month": int(c["as_of"][5:7]),
        "n_filings": len(filings),
        "days_since_filing": days(c["as_of"], last) if last else -1,
        "n_officers": len(r.get("officers") or []),
        "n_psc": len(r.get("psc") or []),
        "address_company_count": r.get("address_company_count") or 0,
        "n_sic": len(r.get("sic_codes") or []),
        "n_unknown": len(r.get("_unknown") or []),
        "status_active": r.get("status") == "active",
        "has_web": bool(web),
        "web_text_len": len(web.get("text") or ""),
        "app_website": bool(app.get("website")),
        "n_search": len((c.get("search") or {}).get("results") or []),
        "n_documents": len(c.get("documents") or []),
        "address_len": len(r.get("registered_address") or ""),
        "n_screen_hits": sum(len(s["candidates"]) for k in ("sanctions", "pep", "disqualified_directors")
                             for s in (c.get("screening") or {}).get(k, [])),
        "n_licences": sum(bool(v) for v in (c.get("licences") or {}).values()),
    }


def main():
    for split in sys.argv[1:]:
        cases = {c["case_id"]: c for c in map(json.loads, open(Path(split) / "cases.jsonl"))}
        labels = json.load(open(Path(split) / "labels.json"))
        feats = {cid: features(c) for cid, c in cases.items()}
        names = list(next(iter(feats.values())))
        clean = [c for c, l in labels.items() if l["channel"] == "none" and l["decision"] == "good"]
        print(f"\n== {split}: {len(cases)} cases, {len(clean)} clean")
        groups = sorted({l["channel"] for l in labels.values()} - {"none", "planted"})
        for g in groups:
            pos = [c for c, l in labels.items() if l["channel"] == g]
            if len(pos) < 5:
                continue
            ids = pos + clean
            y = np.array([1] * len(pos) + [0] * len(clean))
            X = np.array([[float(feats[c][n]) for n in names] for c in ids])
            aucs = {n: roc_auc_score(y, X[:, i]) for i, n in enumerate(names) if X[:, i].std() > 0}
            flagged = {n: round(a, 2) for n, a in sorted(aucs.items(), key=lambda kv: -abs(kv[1] - 0.5)) if abs(a - 0.5) >= 0.2}
            p = cross_val_predict(make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)), X, y,
                                  cv=min(5, len(pos)), method="predict_proba")[:, 1]
            print(f"{g:26} n={len(pos):3}  all-metadata AUC {roc_auc_score(y, p):.2f}  flagged: {flagged}")


if __name__ == "__main__":
    main()
