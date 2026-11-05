"""Copy the public case files to site/data/ with a manifest, for `kybbench download`.

Pilot and validation are published with labels; test splits are published as cases only. Labels
of test splits are refused even if asked for.

    .venv/bin/python scripts/publish_data.py pilot validation test_fresh test_historical
"""

import gzip
import hashlib
import json
import sys
from pathlib import Path

PUBLIC_LABELS = {"pilot", "validation"}
OUT = Path("site/data")
NOTICE = ("Cases are built from public registry records of real UK companies, but every application is "
          "constructed for this benchmark. Some applications contain deliberately altered details. Nothing "
          "in this data implies wrongdoing by any named company or person beyond existing public records.")


def write(src, name):
    data = gzip.compress(Path(src).read_bytes(), mtime=0)
    (OUT / name).write_bytes(data)
    return {"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"splits": {}}
    for split in sys.argv[1:]:
        cases = Path(f"data/{split}/cases.jsonl")
        entry = {"n_cases": sum(1 for _ in open(cases)), "cases": write(cases, f"{split}.cases.jsonl.gz")}
        if split in PUBLIC_LABELS:
            entry["labels"] = write(f"data/{split}/labels.json", f"{split}.labels.json.gz")
        manifest["splits"][split] = entry
        print(split, entry["n_cases"], "cases", "with labels" if "labels" in entry else "(labels hidden)")
    manifest["notice"] = NOTICE
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")


if __name__ == "__main__":
    main()
