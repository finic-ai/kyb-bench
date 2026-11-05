"""Rewrite every company address in a built split to the canonical one-line format
(companies_house.canonical_address), so an address's format cannot reveal how it was rebuilt.
Idempotent.

    .venv/bin/python scripts/fix_addresses.py data/pilot data/validation ...
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench.companies_house import _one_line as canonical_address  # noqa: E402  (accepts str or dict)


def main():
    for split in sys.argv[1:]:
        path = Path(split) / "cases.jsonl"
        rows, changed = [], 0
        for c in map(json.loads, open(path)):
            for section, key in (("registry", "registered_address"), ("application", "registered_address"),
                                 ("application", "trading_address")):
                old = c[section].get(key)
                new = canonical_address(old)
                changed += old != new
                c[section][key] = new
            rows.append(c)
        path.write_text("".join(json.dumps(c) + "\n" for c in rows))
        print(split, len(rows), "cases,", changed, "addresses rewritten")


if __name__ == "__main__":
    main()
