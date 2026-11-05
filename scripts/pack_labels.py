"""Pack a test split's hidden labels for the scoring service (kybbench/server.py).

Writes runs/labels_<split>.b64 (git-ignored). The scoring service reads the packed labels of both
test splits from the Secrets Manager secret kyb-bench-prod/test-labels, as
{"test_fresh": <packed>, "test_historical": <packed>}:

    .venv/bin/python scripts/pack_labels.py test_fresh

The labels never enter the repository or the deployment package.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench import leaderboard  # noqa: E402


def main():
    split = sys.argv[1]
    labels = json.load(open(f"data/{split}/labels.json"))
    blob = leaderboard.pack(labels)
    assert leaderboard.unpack(blob).keys() == labels.keys()
    out = Path(f"runs/labels_{split}.b64")
    out.parent.mkdir(exist_ok=True)
    out.write_text(blob)
    print(f"{len(labels)} labels -> {out} ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
