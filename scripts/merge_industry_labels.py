"""Merge research-agent industry labels into a split's labels (SPEC.md 4.4).

Each labels file is a JSON array of {case_id, company_number, industry, regulated_activity,
licence, confidence, evidence, note}. Regulated companies are re-checked against the FCA register.
High- and medium-confidence labels set a policy floor on the decision (prohibited: bad; high risk:
review); an industry-channel case with only a low-confidence label stays pending and unscored.

    set -a; . ./.env; set +a; .venv/bin/python scripts/merge_industry_labels.py test_fresh 'labels_dir/tf_industry_*.json'
"""

import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import workflow  # noqa: E402
from kybbench.sources import fca  # noqa: E402

SEV = {"good": 0, "review": 1, "bad": 2}
SOURCE = "model-labelled (Claude Opus 5.5 research agents, {}), pending human audit"


def main():
    split, pattern = sys.argv[1], sys.argv[2]
    d = Path(f"data/{split}")
    rows = {r["case_id"]: r for f in sorted(glob.glob(pattern)) for r in json.load(open(f))}
    cases = {c["case_id"]: c for c in map(json.loads, open(d / "cases.jsonl"))}
    labels = json.load(open(d / "labels.json"))
    print("labels:", len(rows), "of", len(labels), "| unknown codes:",
          [r["industry"] for r in rows.values() if r["industry"] not in workflow.INDUSTRIES])
    missing = [c for c, l in labels.items() if l["channel"] == "industry" and c not in rows]
    assert not missing, f"industry-channel cases without a label: {missing}"
    changes = collections.Counter()
    for cid, r in rows.items():
        l = labels[cid]
        industry, licence = r["industry"], r["licence"]
        if r["regulated_activity"] != "none":
            name = cases[cid]["registry"]["name"]
            status = [h.get("Status") for h in fca.search(name) if fca.normalise(h.get("Name")) == fca.normalise(name)]
            if any(s in ("Authorised", "Appointed representative", "Registered") for s in status):
                licence = "held"
                if industry.startswith("P_UNLICENSED"):
                    industry = {"gambling": "H_GAMBLING", "crypto": "H_CRYPTO"}.get(r["regulated_activity"], "H_INVESTMENT")
            print("  FCA", cid, name[:34], r["industry"], "->", industry, r["licence"], "->", licence, status)
        l["industry_label"] = {"industry": industry, "regulated_activity": r["regulated_activity"], "licence": licence,
                               "confidence": r["confidence"], "note": r["note"],
                               "source": SOURCE.format(r.get("labelled_on", "2026-10-30"))}
        l.pop("industry", None)
        if r["confidence"] in ("high", "medium") and industry in workflow.INDUSTRIES:
            l["industry"] = industry
            floor = {"P": "bad", "H": "review"}.get(industry[0], "good")
            new = floor if l["channel"] == "industry" else max(l["decision"], floor, key=SEV.get)
            if new != l["decision"]:
                changes[(l["channel"], l["decision"], new)] += 1
                l["decision"] = new
            l.pop("pending", None)
        elif l["channel"] == "industry":
            l["pending"] = "industry label has low confidence"
    json.dump(labels, open(d / "labels.json", "w"), indent=1)
    json.dump(list(rows.values()), open(d / "industry_evidence.json", "w"), indent=1)
    print("confidence:", dict(collections.Counter(r["confidence"] for r in rows.values())))
    print("decision changes:", dict(changes), "| pending:", sum(bool(l.get("pending")) for l in labels.values()))
    print("decisions:", dict(collections.Counter(l["decision"] for l in labels.values())))


if __name__ == "__main__":
    main()
