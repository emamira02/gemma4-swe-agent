"""Collect the agent's committed results into results/agent_summary.json for the paper (no task text).

    python tools/agent_summary.py

Inputs: results/agent_runs/<tag>.json (dev-panel aggregates from analysis.agent_traces), runs.csv (public
leaderboard scores, one scored run per tag) and results/failure_audit.json (analysis.failure_audit: pooled loss
categories and malformed calls per tool under "failure", plus its "eras", "excluded", "stability" and "by_repo"
blocks). A tag appears under "scored" only once Kaggle has returned a score.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tag_key(tag: str) -> tuple:
    return (tag[:1], int(tag[1:])) if tag[1:].isdigit() else (tag, 0)


def build(runs_dir: Path, runs_csv: Path, audit: Path | None = None) -> dict:
    board = {}
    if runs_csv.exists():
        with runs_csv.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                board[r["experiment_id"]] = r
    panels = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(runs_dir.glob("*.json"))}
    tags = sorted(set(panels) | set(board), key=_tag_key)
    runs, scored = {}, {}
    for t in tags:
        row = {"status": board.get(t, {}).get("status", "NOT_SUBMITTED"), "config_hash": board.get(t, {}).get("config_hash")}
        score = (board.get(t, {}).get("public_score") or "").strip()
        if score:
            row["public_score"] = scored[t] = float(score)
        if t in panels:
            s, cfg = panels[t]["summary"], panels[t].get("config", {})
            repos = sorted({tid.rsplit("_", 1)[0] for tid in panels[t]["per_task"]})
            row["panel"] = {"n": s["n"], "repos": repos, "gold_solvable": s["gold_solvable"],
                            "resolved": s["resolved_on_solvable"],
                            "resolve_rate": round(s["resolved_on_solvable"] / s["gold_solvable"], 6) if s["gold_solvable"] else 0.0,
                            "timeouts": s["timeouts"], "empty_patch": s["empty_patch"], "no_edit": s["no_edit"],
                            "tasks_with_arg_errors": s["tasks_with_arg_errors"],
                            "first_edit_s_median": s["first_edit_s_median"], **{k: s["totals"].get(k, 0) for k in
                                                                               ("calls", "arg_errors", "backtick_args")},
                            **{k: v for k, v in cfg.get("eval_config", {}).items() if k in ("max_time_minutes", "max_tool_calls")}}
        runs[t] = row
    with_panel = [t for t in tags if "panel" in runs[t]]
    doc = {"tags": tags, "runs": runs, "scored": scored, "n_scored": len(scored),
           "n_panels": len(with_panel), "baseline": with_panel[0] if with_panel else None}
    if audit is not None and audit.exists():
        fa = json.loads(audit.read_text(encoding="utf-8"))
        doc["failure"] = fa["aggregate"]
        doc.update({k: fa[k] for k in ("eras", "excluded", "stability", "by_repo") if k in fa})
    return doc


def main() -> int:
    doc = build(ROOT / "results" / "agent_runs", ROOT / "runs.csv", ROOT / "results" / "failure_audit.json")
    out = ROOT / "results" / "agent_summary.json"
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("tags", "scored", "n_panels", "baseline")}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
