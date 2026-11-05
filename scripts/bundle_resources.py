"""Copy the resource files the package reads into kybbench/_bundled, for the PyPI build and the
scoring Lambda. Run before `python -m build`.

    .venv/bin/python scripts/bundle_resources.py
"""

import shutil
from pathlib import Path

FILES = ["data/cost_matrix.json", "data/issue_catalogue.json", "data/policy/v1.md", "questions/v1.json",
         "workflows/v1/questions.json", "workflows/v1/industries.json", *map(str, sorted(Path("prices").glob("*.json")))]
OUT = Path("kybbench/_bundled")


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    for f in FILES:
        (OUT / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, OUT / f)
    print(f"bundled {len(FILES)} files into {OUT}")


if __name__ == "__main__":
    main()
