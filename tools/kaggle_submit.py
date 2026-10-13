"""Build, publish and submit one agent bundle, with an audit trail.

    python tools/kaggle_submit.py --tag S1 --hypothesis "..." [--dry-run]

Steps (any failure stops before submitting):
  1. tools/build_submission.py (full validation, official compile when available, reproducible zip)
  2. refuse if a submission is already pending (Kaggle allows one) or the tag was used before (runs.csv)
  3. push kernels/submit (CPU-only notebook that writes the zip), wait for it to finish
  4. download its output and check the zip is byte-identical (sha256) to the local build
  5. kaggle competitions submit -k <kernel> -v <version> -f submission.zip
  6. append date, tag, sha, kernel version and hypothesis to runs.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMP = "gemma-4-developer-agent"
KERNEL_DIR = ROOT / "kernels" / "submit"
RUNS = ROOT / "runs.csv"


def kaggle(*args: str, timeout: int = 300) -> str:
    # UTF-8 both ways: the CLI prints emoji (kernel logs) that crash a cp1252 console on Windows
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, "-m", "kaggle", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"kaggle {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[-800:]}")
    return r.stdout


def pending_submissions() -> list[str]:
    out = kaggle("competitions", "submissions", COMP, "--csv")
    rows = list(csv.DictReader(out.splitlines())) if out.strip() and "," in out else []
    return [r.get("fileName", "") + " " + r.get("date", "") for r in rows
            if str(r.get("status", "")).upper() not in ("COMPLETE", "SUBMISSIONSTATUS.COMPLETE", "ERROR", "SUBMISSIONSTATUS.ERROR")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--hypothesis", required=True, help="what this submission tests, written before it runs")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if RUNS.exists() and any(r.get("experiment_id") == a.tag for r in csv.DictReader(RUNS.open(encoding="utf-8"))):
        raise SystemExit(f"tag {a.tag} already in runs.csv")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_submission.py"), "--tag", a.tag, "--from-candidate"], check=True)
    manifest = json.loads((ROOT / "build" / "MANIFEST.json").read_text(encoding="utf-8"))
    sha = manifest["zip_sha256"]
    pend = pending_submissions()
    if pend:
        raise SystemExit(f"a submission is still pending ({pend}); Kaggle accepts one at a time")
    if a.dry_run:
        print(f"dry run ok: {a.tag} sha {sha[:12]}")
        return 0
    out = kaggle("kernels", "push", "-p", str(KERNEL_DIR))
    m = re.search(r"version (\d+)", out)
    version = m.group(1) if m else None
    kid = json.loads((KERNEL_DIR / "kernel-metadata.json").read_text(encoding="utf-8"))["id"]
    for _ in range(120):  # CPU notebook: normally < 2 min
        time.sleep(15)
        st = kaggle("kernels", "status", kid)
        if re.search(r"complete", st, re.I):
            break
        if re.search(r"error|cancel", st, re.I):
            raise SystemExit(f"kernel failed: {st.strip()}")
    else:
        raise SystemExit("kernel did not finish in 30 min")
    dl = ROOT / "build" / "kernel_out"
    dl.mkdir(parents=True, exist_ok=True)
    kaggle("kernels", "output", kid, "-p", str(dl), "--force")
    got = hashlib.sha256((dl / "submission.zip").read_bytes()).hexdigest()
    if got != sha:
        raise SystemExit(f"kernel output sha {got[:12]} != local build {sha[:12]}")
    msg = f"{a.tag} sha={sha[:12]} | {a.hypothesis[:200]}"
    args = ["competitions", "submit", COMP, "-k", kid, "-f", "submission.zip", "-m", msg]
    if version:
        args += ["-v", version]
    print(kaggle(*args))
    new = not RUNS.exists() or RUNS.stat().st_size == 0
    with RUNS.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "experiment_id", "config_hash", "public_score", "status", "notes"])
        w.writerow([dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), a.tag, sha[:12], "", "PENDING",
                    f"kernel v{version}; {a.hypothesis}"])
    print(f"submitted {a.tag} ({sha[:12]}), kernel version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
