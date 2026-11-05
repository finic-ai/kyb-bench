"""Run any harness (harnesses/<name>/) with any model on pilot cases, one locked-down container
per case.

    .venv/bin/python scripts/run_container.py build --harness claude-code
    .venv/bin/python scripts/run_container.py check --harness claude-code
    .venv/bin/python scripts/run_container.py run   --harness claude-code --model claude-haiku-5-5 --limit 10

Containers sit on an internal network whose only exit is a proxy allowing just the hosts in the
harness's harness.json. Only the auth variables the harness declares are passed in. Labels never
enter a container; grading is done here.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kybbench import issue_catalogue  # noqa: E402
import run_pilot  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE, PROXY_IMAGE, PROXY = "kybbench-base", "kybbench-proxy", "kybbench-proxy"
INTERNAL, EGRESS = "kybbench-internal", "kybbench-egress"
PROXY_URL = f"http://{PROXY}:8888"


def harness(name, model=None):
    """A harness spec. Harnesses that work with several providers declare egress and auth per
    provider; the model's provider prefix ("provider:model") picks which."""
    spec = json.loads((ROOT / "harnesses" / name / "harness.json").read_text())
    spec = {**spec, "dir": ROOT / "harnesses" / name, "model": model or spec["default_model"]}
    if "by_provider" in spec:
        provider = spec["model"].partition(":")[0]
        if provider not in spec["by_provider"]:
            raise SystemExit(f"{name} supports providers: {', '.join(spec['by_provider'])}")
        spec.update(spec["by_provider"][provider])
    return spec


def auth_env(spec):
    """The first complete set of the harness's auth variables found in the environment."""
    for names in spec["auth_env"]:
        if all(os.environ.get(n) for n in names):
            return [f"{n}={os.environ[n]}" for n in names]
    raise SystemExit(f"{spec['name']} needs one of: " + " | ".join("+".join(n) for n in spec["auth_env"]))


def docker(*args, check=True, capture=False):
    return subprocess.run(["docker", *args], check=check, text=True,
                          capture_output=capture, timeout=900)


def build(spec):
    docker("build", "-t", BASE_IMAGE, str(ROOT / "docker/base"))
    docker("build", "-t", PROXY_IMAGE, str(ROOT / "docker/proxy"))
    if "context" in spec:  # harnesses that need repo code build from the repo root (.dockerignore applies)
        docker("build", "-t", spec["image"], "-f", str(spec["dir"] / "Dockerfile"), str(ROOT / spec["context"]))
    else:
        docker("build", "-t", spec["image"], str(spec["dir"]))


def network_up(spec):
    """Networks, and a proxy whose allow list is exactly the harness's declared hosts."""
    allow = ROOT / "runs" / f"proxy-allow-{spec['name']}"
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text("".join("^" + h.replace(".", r"\.") + "$\n" for h in spec["egress"]))
    have = docker("network", "ls", "--format", "{{.Name}}", capture=True).stdout.split()
    if INTERNAL not in have:
        docker("network", "create", "--internal", INTERNAL)
    if EGRESS not in have:
        docker("network", "create", EGRESS)
    docker("rm", "-f", PROXY, check=False, capture=True)
    docker("run", "-d", "--name", PROXY, "--network", EGRESS, "--read-only", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "-v", f"{allow}:/etc/tinyproxy/allow:ro", PROXY_IMAGE)
    docker("network", "connect", INTERNAL, PROXY)


def _locked(image, extra_env=(), mounts=(), entry=None):
    args = ["run", "--rm", "--network", INTERNAL,
            "-e", f"HTTPS_PROXY={PROXY_URL}", "-e", f"HTTP_PROXY={PROXY_URL}", "-e", "NO_PROXY=localhost,127.0.0.1",
            "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/home/agent:uid=1000,gid=1000",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256", "--memory", "2g", "--cpus", "1"]
    for e in extra_env:
        args += ["-e", e]
    for m in mounts:
        args += ["-v", m]
    if entry:
        args += ["--entrypoint", entry[0]]
    return args + [image] + list(entry[1:] if entry else [])


def check(spec):
    """A container must reach the harness's declared hosts through the proxy and nothing else."""
    network_up(spec)
    probe = ("import urllib.request, sys\n"
             "for url in sys.argv[1:]:\n"
             "    try:\n"
             "        urllib.request.urlopen(url, timeout=10); print('REACHED', url)\n"
             "    except urllib.error.HTTPError as e: print('REACHED', url, e.code)\n"
             "    except Exception as e: print('BLOCKED', url, type(e).__name__)\n")
    allowed = [f"https://{h}/" for h in spec["egress"]]
    denied = ["https://www.google.com", "https://find-and-update.company-information.service.gov.uk",
              "https://www.thegazette.co.uk", "https://web.archive.org"]
    out = docker(*_locked(spec["image"], entry=["python3", "-c", probe, *allowed, *denied]), capture=True).stdout
    print(out)
    direct = docker(*_locked(spec["image"], extra_env=["HTTPS_PROXY=", "HTTP_PROXY="],
                             entry=["python3", "-c", probe, (allowed or denied)[0]]), capture=True).stdout
    print("without the proxy:", direct)
    ok = (all(f"REACHED {u}" in out for u in allowed) and all(f"BLOCKED {u}" in out for u in denied)
          and "BLOCKED" in direct)
    print("lockdown OK" if ok else "LOCKDOWN FAILED")
    return ok


def run_case(spec, case, model, auth, out_root):
    work = Path(tempfile.mkdtemp(prefix="kyb-"))
    (work / "case").mkdir()
    (work / "out").mkdir()
    (work / "case/case.json").write_text(json.dumps(case))
    os.chmod(work / "out", 0o777)
    start = time.monotonic()
    proc = subprocess.run(["docker", *_locked(spec["image"], extra_env=[*auth, f"KYB_MODEL={model}"],
                                              mounts=[f"{work / 'case'}:/case:ro", f"{work / 'out'}:/out"])],
                          text=True, capture_output=True, timeout=1800)
    wall_ms = int((time.monotonic() - start) * 1000)
    pred_path, tr_path = work / "out/prediction.json", work / "out/trace.json"
    tr = json.loads(tr_path.read_text()) if tr_path.exists() and tr_path.stat().st_size else {}
    turns = tr.get("turns") or 0
    trace = {"case_id": case["case_id"], "run_id": out_root.name,
             "system": {"name": out_root.name, "version": model, "type": "llm", "mode": "agent", "harness": spec["name"]},
             "spans": [{"type": "llm_call", "model": model, "input_tokens": tr.get("input_tokens", 0),
                        "output_tokens": tr.get("output_tokens", 0), "latency_ms": tr.get("duration_ms") or wall_ms}],
             "totals": {"wall_ms": wall_ms, "calls": turns, "tool_calls": max(0, turns - 1),
                        "input_tokens": tr.get("input_tokens", 0), "output_tokens": tr.get("output_tokens", 0),
                        "cost_usd": tr.get("cost_usd")}}
    if pred_path.exists():
        pred = json.loads(pred_path.read_text())
    else:
        pred = {"case_id": case["case_id"], "score": 0.5, "decision": "review", "industry": "L_OTHER",
                "risk_rating": "high", "issues": {c: 0.0 for c in issue_catalogue()}, "failed": True,
                "error": (tr.get("error") or proc.stderr or "no prediction")[-400:]}
    shutil.rmtree(work, ignore_errors=True)
    return pred, trace


def run(spec, limit, workers):
    model = spec["model"]
    auth = auth_env(spec)
    if not check(spec):
        raise SystemExit("refusing to run: network lockdown check failed")
    cases = [json.loads(l) for l in open(run_pilot.PILOT / "cases.jsonl")][:limit]
    labels = {k: v for k, v in json.load(open(run_pilot.PILOT / "labels.json")).items() if k in {c["case_id"] for c in cases}}
    out = run_pilot.RUNS / f"agent-{spec['name']}-{model.replace(':', '-').replace('/', '-')}"
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda c: run_case(spec, c, model, auth, out), cases))
    preds = {p["case_id"]: p for p, _ in results}
    traces = {t["case_id"]: t for _, t in results}
    (out / "predictions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in preds.values()))
    (out / "traces.jsonl").write_text("".join(json.dumps(t) + "\n" for t in traces.values()))
    n_failed = sum(bool(p.get("failed")) for p in preds.values())
    rep = {"system": traces[cases[0]["case_id"]]["system"], "run_seconds": round(time.monotonic() - start, 1),
           **run_pilot.report(labels, preds, traces, json.load(open("prices/2026-10.json")), n_failed)}
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "check", "run"])
    ap.add_argument("--harness", default="claude-code", help="folder name under harnesses/")
    ap.add_argument("--model", help="defaults to the harness's default_model")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    spec = harness(a.harness, a.model)
    {"build": lambda: build(spec), "check": lambda: check(spec),
     "run": lambda: run(spec, a.limit, a.workers)}[a.cmd]()


if __name__ == "__main__":
    main()
