"""Compare search sources on the pilot: usable results per case (Wayback capture on or before
as_of that names the company) from Brave, Google via SerpAPI, and both combined. Read-only.

    set -a; . ./.env; set +a; .venv/bin/python scripts/compare_search.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_search import _SUFFIX, mentions  # noqa: E402
from kybbench.sources import brave, serpapi, wayback  # noqa: E402


def usable(urls, name, as_of):
    out = set()
    for u in urls:
        cap = wayback.capture_before(u, as_of)
        if cap and mentions(wayback.page_text(*cap), name):
            out.add(cap[1])
    return out


def queries(name):
    core = _SUFFIX.sub("", name).strip(" .,")
    return [f'"{name}"'] + ([f'"{core}"'] if core and core != name else [])


def main():
    cases = [json.loads(l) for l in open("data/pilot/cases.jsonl")]
    labels = json.load(open("data/pilot/labels.json"))
    rows, by_channel = [], {}
    for c in cases:
        name, as_of = c["registry"]["name"], c["as_of"]
        b = usable([u for q in queries(name) for u in brave.search(q)], name, as_of)
        g = usable([u for q in queries(name) for u in serpapi.search(q)], name, as_of)
        rows.append((c["case_id"], len(b), len(g), len(b | g)))
        by_channel.setdefault(labels[c["case_id"]]["channel"], []).append((len(b), len(g), len(b | g)))
        print(c["case_id"], "brave", len(b), "google", len(g), "both", len(b | g), flush=True)
    n = len(rows)
    for i, src in ((1, "brave"), (2, "google"), (3, "both")):
        vals = [r[i] for r in rows]
        print(f"{src:7} cases with >=1 usable result: {sum(v > 0 for v in vals)}/{n} | mean usable per case {sum(vals)/n:.2f}")
    for ch, v in sorted(by_channel.items()):
        print(f"  {ch:17} brave {sum(x[0] > 0 for x in v)}/{len(v)} | google {sum(x[1] > 0 for x in v)}/{len(v)} | both {sum(x[2] > 0 for x in v)}/{len(v)}")


if __name__ == "__main__":
    main()
