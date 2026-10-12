"""Single idempotent resume point for the Kaggle loop. Safe to run any time, any number of times, after a reboot.

    python tools/status.py            # sync everything, print the state, write STATE.json
    python tools/status.py --quiet    # same, only the one-line summary

1. Submissions: fetch Kaggle submissions; fill public_score / status into runs.csv for our tags (matched by the
   "Sx sha=" prefix of the description). Writes are atomic (tmp file + replace).
2. Dev-panel eval kernel: if the last pushed version finished and its outputs are not on disk yet, download them to
   results/kaggle_eval_<tag>/ and aggregate the traces into results/agent_runs/<tag>.json.
3. Writes STATE.json (machine-readable) and prints what is running, what finished and the next action.
A lock file prevents two concurrent runs (scheduled task + manual run).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMP = "gemma-4-developer-agent"
EVAL_KERNEL = "emanuelemiranda/g4-agent-eval"
RUNS = ROOT / "runs.csv"
STATE = ROOT / "STATE.json"
LOCK = ROOT / ".status.lock"


def kaggle(*args: str, timeout: int = 600) -> str:
    # UTF-8 both ways: the CLI prints emoji (kernel logs) that crash a cp1252 console on Windows
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, "-m", "kaggle", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"kaggle {' '.join(args)}: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def sync_submissions() -> list[dict]:
    out = kaggle("competitions", "submissions", COMP, "--csv")
    subs = list(csv.DictReader(out.splitlines())) if "," in out else []
    if not RUNS.exists():
        return subs
    rows = list(csv.DictReader(RUNS.open(encoding="utf-8")))
    fields = list(rows[0].keys()) if rows else ["date", "experiment_id", "config_hash", "public_score", "notes"]
    if "status" not in fields:
        fields.insert(4, "status")
    for r in rows:
        tag = r["experiment_id"]
        m = next((s for s in subs if re.match(rf"{re.escape(tag)} sha=", s.get("description", ""))), None)
        if m:
            r["status"] = str(m.get("status", "")).replace("SubmissionStatus.", "")
            if m.get("publicScore"):
                r["public_score"] = m["publicScore"]
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields})
    atomic_write(RUNS, buf.getvalue())
    return subs


def sync_eval() -> dict:
    panel = json.loads((ROOT / "kernels" / "agent_eval" / "panel.json").read_text(encoding="utf-8"))
    tag = panel["tag"]
    st = kaggle("kernels", "status", EVAL_KERNEL).strip()
    status = re.sub(r'.*has status "?(?:KernelWorkerStatus\.)?([A-Za-z_]+)"?.*', r"\1", st, flags=re.S)
    dest = ROOT / "results" / f"kaggle_eval_{tag}"
    info = {"tag": tag, "kernel_status": status, "downloaded": (dest / "agent_eval" / "summary.json").exists()}
    if status.upper() == "COMPLETE" and not info["downloaded"]:
        dest.mkdir(parents=True, exist_ok=True)
        kaggle("kernels", "output", EVAL_KERNEL, "-p", str(dest), "--force", timeout=1800)
        info["downloaded"] = (dest / "agent_eval" / "summary.json").exists()
    if info["downloaded"]:
        out = ROOT / "results" / "agent_runs" / f"{tag}.json"
        if not out.exists():
            subprocess.run([sys.executable, "-m", "analysis.agent_traces", str(dest), "--out", str(out)], cwd=ROOT,
                           check=True, capture_output=True)
        info["summary"] = json.loads(out.read_text(encoding="utf-8"))["summary"]
    return info


def main() -> int:
    quiet = "--quiet" in sys.argv
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        age = dt.datetime.now().timestamp() - LOCK.stat().st_mtime
        if age < 3600:
            print("another status run is in progress (lock < 1 h old); exiting")
            return 0
        LOCK.unlink()  # stale lock from a crash or reboot
        return main()
    try:
        state = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "errors": []}
        try:
            subs = sync_submissions()
            state["submissions"] = [{k: s.get(k) for k in ("ref", "date", "description", "status", "publicScore")} for s in subs]
            state["pending_submission"] = any("PENDING" in str(s.get("status", "")).upper() or "RUNNING" in str(s.get("status", "")).upper()
                                              for s in subs)
        except Exception as e:
            state["errors"].append(f"submissions: {e}")
        try:
            state["eval"] = sync_eval()
        except Exception as e:
            state["errors"].append(f"eval: {e}")
        runs = list(csv.DictReader(RUNS.open(encoding="utf-8"))) if RUNS.exists() else []
        state["runs"] = runs
        atomic_write(STATE, json.dumps(state, indent=1))
        ev = state.get("eval", {})
        line = (f"[{state['utc']}] pending_submission={state.get('pending_submission')} | eval {ev.get('tag')}: "
                f"{ev.get('kernel_status')} downloaded={ev.get('downloaded')}"
                + (f" resolved {ev['summary']['resolved_on_solvable']}/{ev['summary']['gold_solvable']}" if ev.get("summary") else "")
                + " | scores: " + ", ".join(f"{r['experiment_id']}={r.get('public_score') or r.get('status') or '?'}" for r in runs)
                + (f" | ERRORS: {state['errors']}" if state["errors"] else ""))
        print(line if quiet else json.dumps({k: v for k, v in state.items() if k != "submissions"}, indent=1) + "\n" + line)
        return 1 if state["errors"] else 0
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
