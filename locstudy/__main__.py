"""python -m locstudy {run,sensitivity,report,all} [--data data] [--results results] [--paper paper]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report, study

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="locstudy")
    ap.add_argument("cmd", choices=["run", "sensitivity", "report", "llm", "all"])
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--results", type=Path, default=ROOT / "results")
    ap.add_argument("--paper", type=Path, default=ROOT / "paper")
    a = ap.parse_args(argv)
    log = lambda *m: print(*m, file=sys.stderr, flush=True)  # noqa: E731
    if a.cmd in ("run", "all"):
        study.run(a.data, a.results, log=log)
    if a.cmd in ("sensitivity", "all"):
        study.sensitivity(a.data, a.results, log=log)
    if a.cmd == "llm":
        from . import llm_analysis
        src = a.results / "kaggle_v2"
        llm_analysis.analyze(src / "llm_rows.jsonl", src / "llm_meta.json", a.results / "llm_summary.json")
        log("wrote results/llm_summary.json")
    if a.cmd in ("report", "all", "llm"):
        report.build(a.results, a.paper)
        log(f"wrote {a.paper / 'RESULTS.md'} and figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
