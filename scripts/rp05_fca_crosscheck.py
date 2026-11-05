"""Cross-check companies the registrar moved to the default address against the FCA Register.

Stage 1 (Companies House thread): for every active company at the default address, find the
date the default address was applied (RP05). Companies moved on or after WINDOW_FROM go to
stage 2.
Stage 2 (FCA thread): look each one up in the FCA Register and record Unauthorised matches.

Resumable: progress is appended to data/labels/raw/rp05_dates.jsonl and rp05_fca.jsonl.

    set -a; . ./.env; set +a; .venv/bin/python scripts/rp05_fca_crosscheck.py
"""

import json
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kybbench.sources import fca, registrar  # noqa: E402

WINDOW_FROM = "2026-08-03"
RAW = Path("data/labels/raw")
COMPANIES = RAW / "default_address_active.jsonl"
DATES = RAW / "rp05_dates.jsonl"
FCA = RAW / "rp05_fca.jsonl"


def _read(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def main():
    companies = _read(COMPANIES)
    dated = {r["company_number"]: r for r in _read(DATES)}
    checked = {r["company_number"] for r in _read(FCA)}
    todo_fca = queue.Queue()
    for r in dated.values():
        if r["rp05"] and r["rp05"] >= WINDOW_FROM and r["company_number"] not in checked:
            todo_fca.put(r)
    done = threading.Event()
    lock = threading.Lock()
    counts = {"dated": len(dated), "fresh": sum(1 for r in dated.values() if r["rp05"] and r["rp05"] >= WINDOW_FROM),
              "fca_checked": len(checked), "fca_hits": sum(1 for r in _read(FCA) if r["matches"])}

    def ch_worker():
        for c in companies:
            num = c["company_number"]
            if num in dated:
                continue
            try:
                d = registrar.default_address_applied(num)
            except Exception as e:  # keep going; failures are retried on the next run
                print(f"CH error {num}: {e}", flush=True)
                continue
            row = {"company_number": num, "company_name": c["company_name"], "rp05": d,
                   "incorporated": c.get("date_of_creation"), "sic_codes": c.get("sic_codes")}
            with lock, DATES.open("a") as f:
                f.write(json.dumps(row) + "\n")
                counts["dated"] += 1
                if d and d >= WINDOW_FROM:
                    counts["fresh"] += 1
                    todo_fca.put(row)
        done.set()

    def fca_worker():
        while not (done.is_set() and todo_fca.empty()):
            try:
                row = todo_fca.get(timeout=5)
            except queue.Empty:
                continue
            try:
                matches = fca.unauthorised_matches(row["company_name"])
            except Exception as e:
                print(f"FCA error {row['company_number']}: {e}", flush=True)
                continue
            with lock, FCA.open("a") as f:
                f.write(json.dumps({**row, "matches": matches}) + "\n")
                counts["fca_checked"] += 1
                counts["fca_hits"] += bool(matches)

    threads = [threading.Thread(target=ch_worker), threading.Thread(target=fca_worker)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(300)
        with lock:
            print(f"{time.strftime('%H:%M')} dated {counts['dated']}/{len(companies)} | fresh {counts['fresh']} "
                  f"| FCA checked {counts['fca_checked']} | FCA unauthorised matches {counts['fca_hits']}", flush=True)
    print("finished", counts, flush=True)


if __name__ == "__main__":
    main()
