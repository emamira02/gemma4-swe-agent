"""Submit the next entry of submit_queue.json, if today's slot is free. Idempotent; safe to run every few hours.

    python tools/submit_next.py [--dry-run]

Owner policy (Emanuele, 2026-10-27): one submission every UTC day, each a new version that fixes the previous
one's failures. submit_queue.json lists the versions in the order they ship ({"tag", "hypothesis", "added"});
an interactive session appends the day's new version after freezing it and running tools/release_gate.py.
This script submits the first queued tag that is not in runs.csv, only when
  - no submission was made today (UTC) and none is pending (Kaggle accepts one at a time), and
  - the tag passes the release gate (its own dev-panel SANITY or a passing GATE.json; tools/kaggle_submit.py
    enforces it again).
It never skips a queued tag silently: a tag that fails the gate stops the queue and is reported.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
QUEUE = ROOT / "submit_queue.json"
RUNS = ROOT / "runs.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    from tools.kaggle_submit import pending_submissions
    from tools.release_gate import submittable
    runs = list(csv.DictReader(RUNS.open(encoding="utf-8"))) if RUNS.exists() else []
    used = {r.get("experiment_id") for r in runs}
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if any((r.get("date") or "").startswith(today) for r in runs):
        print(f"already submitted today ({today} UTC): nothing to do")
        return 0
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    nxt = next((q for q in queue if q["tag"] not in used), None)
    if nxt is None:
        print("submit queue exhausted: freeze, gate and queue the next version")
        return 3
    pend = pending_submissions()
    if pend:
        print(f"a submission is pending ({pend}); next in queue: {nxt['tag']}")
        return 0
    man = json.loads((ROOT / "candidates" / nxt["tag"] / "MANIFEST.json").read_text(encoding="utf-8"))
    ok, why = submittable(nxt["tag"], man["zip_sha256"])
    if not ok:
        print(f"queue STOPPED: {nxt['tag']} fails the release gate ({why}); a human decision is needed")
        return 4
    cmd = [sys.executable, str(ROOT / "tools" / "kaggle_submit.py"), "--tag", nxt["tag"], "--hypothesis", nxt["hypothesis"]]
    if a.dry_run:
        cmd.append("--dry-run")
    print("running:", " ".join(cmd[1:4]), "...")
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
