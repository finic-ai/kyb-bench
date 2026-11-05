"""Re-derive each case's company status at as_of (after a fix to the rule in companies_house) and
label any company dissolved on its case date as bad with STATUS_MISMATCH: a dissolved company
cannot apply.

    KYB_SPLIT=data/validation .venv/bin/python scripts/fix_status.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import companies_house as ch  # noqa: E402

SPLIT = Path(os.environ.get("KYB_SPLIT", "data/pilot"))


def main():
    cases = [json.loads(l) for l in open(SPLIT / "cases.jsonl")]
    labels = json.load(open(SPLIT / "labels.json"))
    for c in cases:
        status = ch.snapshot(c["registry"]["company_number"], c["as_of"])["status"]
        if status != c["registry"]["status"]:
            print(f"{c['case_id']}: {c['registry']['status']} -> {status}")
            c["registry"]["status"] = status
        lab = labels[c["case_id"]]
        if status not in ("active", None) and lab["decision"] != "bad":
            lab.update(decision="bad", issues=sorted(set(lab["issues"]) | {"STATUS_MISMATCH"}),
                       note="dissolved on the case date")
    (SPLIT / "cases.jsonl.tmp").write_text("".join(json.dumps(x) + "\n" for x in cases))
    (SPLIT / "cases.jsonl.tmp").replace(SPLIT / "cases.jsonl")
    json.dump(labels, open(SPLIT / "labels.json", "w"), indent=1)


if __name__ == "__main__":
    main()
