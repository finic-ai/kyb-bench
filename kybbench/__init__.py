"""KYB-Bench: decide whether to onboard a business, scored on decision quality and cost."""

import json
from pathlib import Path

__version__ = "0.1.0"

# Resources (cost matrix, issue catalogue, policy, workflow questions, prices) live at the repository
# root; an installed package carries copies in kybbench/_bundled (scripts/bundle_resources.py).
_REPO = Path(__file__).resolve().parents[1]
ROOT = _REPO if (_REPO / "data/cost_matrix.json").exists() else Path(__file__).resolve().parent / "_bundled"


def load_json(rel):
    return json.loads((ROOT / rel).read_text())


def issue_catalogue():
    return load_json("data/issue_catalogue.json")["issues"]


def cost_matrix():
    return load_json("data/cost_matrix.json")["cost"]
