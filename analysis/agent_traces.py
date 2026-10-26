"""Aggregate a dev-panel run of the agent (kernels/agent_eval output) into behaviour metrics. No task text is kept.

    python -m analysis.agent_traces results/kaggle_eval_S1 [--out results/agent_runs/S1.json]

Per task: resolved / gold-solvable, tool calls by name, argument errors (INVALID_ARGUMENTS, unreadable paths,
missing mandatory params), calls with backticks in arguments, identical consecutive calls, time of the first edit,
completion tokens and latency per step, session timeout, calls after submit_patch. From S6 on, edits also arrive as
run_command calls of the heredoc editor (edit.py): they count as edits, plus how often the editor refused a block and
how often the heredoc was left unquoted.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
from collections import Counter
from pathlib import Path

ARG_ERRORS = ("INVALID_ARGUMENTS", "FileReadError", "mandatory input")
EDITOR_RX = re.compile(r"\bedit\.py\s+[^\s<]")
UNQUOTED_RX = re.compile(r"edit\.py[^\n]*<<-?\s*[A-Za-z_]")


def is_edit(name: str, args: dict) -> bool:
    return name in ("edit_file", "write_file") or (name == "run_command" and bool(EDITOR_RX.search(str(args.get("command", "")))))


def task_metrics(trace: dict) -> dict:
    c: Counter = Counter()
    prev, submitted, first_edit, lat, comp, t_prev = None, False, None, [], [], None
    for s in trace["steps"]:
        if s.get("source") != "agent":
            continue
        e = (s.get("extra") or {}).get("elapsed_s")
        if e is not None and t_prev is not None:
            lat.append(e - t_prev)
        t_prev = e if e is not None else t_prev
        if (s.get("metrics") or {}).get("completion_tokens"):
            comp.append(s["metrics"]["completion_tokens"])
        obs = (s.get("observation") or {}).get("content", "")
        for tc in s.get("tool_calls") or []:
            name, args = tc["function_name"], json.dumps(tc["arguments"], sort_keys=True)
            c["calls"] += 1
            c[f"tool:{name}"] += 1
            c["after_submit"] += submitted
            submitted |= name == "submit_patch"
            c["backtick_args"] += "`" in args
            c["arg_errors"] += any(x in obs for x in ARG_ERRORS)
            c["identical_repeat"] += (name, args) == prev
            prev = (name, args)
            if name == "run_command" and EDITOR_RX.search(str(tc["arguments"].get("command", ""))):
                c["editor_calls"] += 1
                c["editor_not_applied"] += "EDIT NOT APPLIED" in obs
                c["editor_missing"] += "can't open file" in obs or "No such file or directory" in obs
                c["editor_unquoted"] += bool(UNQUOTED_RX.search(tc["arguments"]["command"]))
            if is_edit(name, tc["arguments"]) and first_edit is None:
                first_edit = round(tc["extra"]["elapsed_s"], 1)
    return {**c, "first_edit_s": first_edit, "steps": len(comp),
            "completion_tokens_median": st.median(comp) if comp else 0, "latency_median_s": round(st.median(lat), 2) if lat else 0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    ev = a.run_dir / "agent_eval"
    rows = {json.loads(l)["id"]: json.loads(l) for l in (ev / "per_task.jsonl").read_text().splitlines() if l.strip()}
    per = {}
    for tid, r in sorted(rows.items()):
        tp = ev / "results" / "traces" / f"trace_{tid}.json"
        m = task_metrics(json.loads(tp.read_text(encoding="utf-8"))) if tp.exists() else {}
        per[tid] = {"resolved": r["agent"].get("resolved"), "gold": r["gold"].get("resolved"),
                    "timeout": "timeout" in (r["agent"].get("error") or ""), "patch_chars": r["agent"].get("patch_chars"),
                    "duration_s": r["agent"].get("duration_s"), **m}
    solv = [v for v in per.values() if v["gold"]]
    tot = Counter()
    for v in per.values():
        tot.update({k: v[k] for k in ("calls", "arg_errors", "backtick_args", "identical_repeat", "after_submit",
                                      "editor_calls", "editor_not_applied", "editor_unquoted", "editor_missing")
                    if k in v})
    summary = {"n": len(per), "gold_solvable": len(solv), "resolved_on_solvable": sum(bool(v["resolved"]) for v in solv),
               "timeouts": sum(v["timeout"] for v in per.values()), "empty_patch": sum(not v["patch_chars"] for v in per.values()),
               "tasks_with_arg_errors": sum(bool(v.get("arg_errors")) for v in per.values()),
               "first_edit_s_median": st.median([v["first_edit_s"] for v in per.values() if v.get("first_edit_s") is not None] or [0]),
               "no_edit": sum(v.get("first_edit_s") is None for v in per.values()), "totals": dict(tot)}
    sp = ev / "summary.json"  # kernel summary: bundle sha and the eval_config budgets the panel ran with
    ks = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    config = {k: ks[k] for k in ("tag", "sha256", "eval_config") if k in ks}
    out = {"summary": summary, "config": config, "per_task": per}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
