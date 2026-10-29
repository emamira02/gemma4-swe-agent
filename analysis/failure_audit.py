"""Per-task failure taxonomy of dev-panel runs: where along issue -> localization -> edit -> patch each task was lost.

    python -m analysis.failure_audit [--tags S1 S2 S3 S4] [--out results/failure_audit.json]

Inputs: results/kaggle_eval_<tag>/agent_eval/{per_task.jsonl, results/traces/*.json} and the gold patches in
data/tasks.jsonl (read locally, never copied: the output keeps task ids, file-level booleans and counts only).
Output: {"by_tag": {tag: {"counts", "per_task"}}, "aggregate": pooled task runs of the edit_file era (or of all
tags if none of it was audited), "eras": pooled runs per era (ERAS), "excluded": tags kept out of every era and why,
"stability": per-task outcome agreement over all runs, "by_repo": resolved/solvable per repository of mixed panels}.

Categories, first match wins (denominator = all panel tasks; "solvable" = the gold patch resolves the task):
  GOLD_UNSOLVABLE      the reference patch itself fails in the panel environment
  RESOLVED             hidden tests pass
  NO_EDIT_TOOL         no successful write to a non-test source file, >= 2 edit attempts failed at the tool level
                       (a malformed call, or from S6 the heredoc editor refusing the block or not being found)
  NO_EDIT              no successful write to a non-test source file
  WRONG_FILE           successful writes, none to a file the gold patch changes
  RIGHT_FILE_TOOL      a gold file was written, the run timed out and >= 3 edit attempts were malformed
  RIGHT_FILE_TIMEOUT   a gold file was written, the run timed out
  RIGHT_FILE_WRONG_FIX a gold file was written and the patch was submitted, but the hidden tests fail
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
EDITOR_CMD = re.compile(r"\bedit\.py\s+([^\s<]+)")
WRITE_CMD = re.compile(r"(?:sed\s+-i\S*\s.*?|>\s*|tee\s+(?:-a\s+)?)([\w./-]+\.py)\b")
EXPECTED = {"run_command": {"command"}, "read_file": {"filepath", "start_line", "end_line"},
            "edit_file": {"filepath", "old_string", "new_string", "allow_multiple"}, "write_file": {"filepath", "content"},
            "run_skill_script": {"args", "file_path", "skill_name"}, "submit_patch": set(), "get_status": set()}
REQUIRED = {"run_command": {"command"}, "read_file": {"filepath"}, "edit_file": {"filepath", "old_string", "new_string"},
            "write_file": {"filepath", "content"}, "run_skill_script": {"file_path", "skill_name"}}
CATEGORIES = ("GOLD_UNSOLVABLE", "RESOLVED", "NO_EDIT_TOOL", "NO_EDIT", "WRONG_FILE", "RIGHT_FILE_TOOL", "RIGHT_FILE_TIMEOUT",
              "RIGHT_FILE_WRONG_FIX")
# Runs are pooled only within one edit channel: edit_file (two code-valued arguments) up to S5, the single-argument
# heredoc editor from S7, and the public Budget-Fit prompt (edit_file) as B1. Two tags stay out of every era.
ERAS = {"edit_file": ("S1", "S2", "S3", "S4", "S5"), "editor": ("S7", "S8", "S9", "S12"), "public_prompt": ("B1",)}
EXCLUDED = {"S6": "editor unreachable in 15 tasks (infrastructure, fixed in S7)",
            "S13": "targeted panel: 11 selected failures and 3 controls"}


def gold_files(patch: str) -> set[str]:
    return {m for m in re.findall(r"^\+\+\+ b/(\S+)", patch, re.M) if not TEST_PATH.search(m)}


def malformed(name: str, args: dict) -> bool:
    keys = set(args)
    return bool(keys - EXPECTED.get(name, keys)) or bool(REQUIRED.get(name, set()) - keys)


def _norm(p: str) -> str:
    p = p.strip().strip("'\"")
    return p[len("/workspace/"):] if p.startswith("/workspace/") else p.lstrip("./")


def _status(obs: str) -> str | None:
    try:
        j = json.loads(obs)
    except (ValueError, TypeError):
        return None
    return j.get("status") if isinstance(j, dict) else None


def trace_facts(trace: dict, gold: set[str]) -> dict:
    written, read, bad, edits, bad_edits, rank = set(), set(), 0, 0, 0, None
    tools: dict[str, list[int]] = {}  # name -> [calls, malformed calls]
    for s in trace["steps"]:
        obs = (s.get("observation") or {}).get("content", "")
        for tc in s.get("tool_calls") or []:
            name, a = tc["function_name"], tc["arguments"]
            editor = name == "run_command" and EDITOR_CMD.search(str(a.get("command", "")))
            is_edit = name in ("edit_file", "write_file") or bool(editor)
            edits += is_edit
            t = tools.setdefault(name, [0, 0])
            t[0] += 1
            if malformed(name, a):
                t[1] += 1
                bad += 1
                bad_edits += is_edit
                continue
            st = _status(obs)
            if name in ("edit_file", "write_file") and st == "ok":
                written.add(_norm(a["filepath"]))
            elif name == "read_file" and st == "ok":
                read.add(_norm(a["filepath"]))
            elif editor:
                if st == "ok" and ("APPLIED to" in obs or "CREATED " in obs):
                    written.add(_norm(editor.group(1)))
                elif "EDIT NOT APPLIED" in obs or "can't open file" in obs or "No such file or directory" in obs:
                    bad_edits += 1  # refused block, or the editor was not where the command looked for it
            elif name == "run_command":
                written.update(_norm(m) for m in WRITE_CMD.findall(a["command"]))
            elif name == "run_skill_script" and "localize" in str(a.get("file_path")) and rank is None:
                hits = re.findall(r"^\s*(\d+)\. ([^\s:]+):\d+", json.loads(obs).get("stdout", "") if _status(obs) == "success"
                                  else "", re.M)
                ranks = [int(i) for i, p in hits if p in gold]
                rank = min(ranks) if ranks else (0 if hits else None)  # 0 = listed, gold file absent
    src = {p for p in written if not TEST_PATH.search(p) and p.endswith(".py") and "/" in p}
    return {"wrote_source": bool(src), "wrote_gold": bool(src & gold), "read_gold": bool(read & gold),
            "malformed_calls": bad, "edit_attempts": edits, "malformed_edits": bad_edits,
            "localize_gold_file_rank": rank, "calls_by_tool": tools}


def classify(r: dict, f: dict) -> str:
    if not r["gold"]["resolved"]:
        return "GOLD_UNSOLVABLE"
    if r["agent"]["resolved"]:
        return "RESOLVED"
    if not f["wrote_source"]:
        return "NO_EDIT_TOOL" if f["malformed_edits"] >= 2 else "NO_EDIT"
    if not f["wrote_gold"]:
        return "WRONG_FILE"
    if "timeout" in (r["agent"].get("error") or ""):
        return "RIGHT_FILE_TOOL" if f["malformed_edits"] >= 3 else "RIGHT_FILE_TIMEOUT"
    return "RIGHT_FILE_WRONG_FIX"


def audit(tag: str, golds: dict[str, set[str]]) -> dict:
    ev = ROOT / "results" / f"kaggle_eval_{tag}" / "agent_eval"
    per = {}
    for line in (ev / "per_task.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        tp = ev / "results" / "traces" / f"trace_{r['id']}.json"
        f = trace_facts(json.loads(tp.read_text(encoding="utf-8")), golds[r["id"]]) if tp.exists() else {
            "wrote_source": False, "wrote_gold": False, "read_gold": False, "malformed_calls": 0, "edit_attempts": 0,
            "malformed_edits": 0, "localize_gold_file_rank": None, "calls_by_tool": {}}
        per[r["id"]] = {"category": classify(r, f), **f}
    counts = Counter(v["category"] for v in per.values())
    return {"counts": {c: counts.get(c, 0) for c in CATEGORIES}, "per_task": per}


def aggregate(by_tag: dict) -> dict:
    """Pooled over every task run of every tag; rates are over gold-solvable runs unless named otherwise."""
    runs = [v for t in by_tag.values() for v in t["per_task"].values()]
    solv = [v for v in runs if v["category"] != "GOLD_UNSOLVABLE"]
    unres = [v for v in solv if v["category"] != "RESOLVED"]
    tools: dict[str, list[int]] = {}
    for v in runs:
        for name, (n, bad) in v["calls_by_tool"].items():
            t = tools.setdefault(name, [0, 0])
            t[0], t[1] = t[0] + n, t[1] + bad
    resolved = [t["counts"]["RESOLVED"] for t in by_tag.values()]
    rank1 = sum(v["localize_gold_file_rank"] == 1 for v in solv)
    cats = Counter(v["category"] for v in unres)
    calls, bad = sum(c for c, _ in tools.values()), sum(b for _, b in tools.values())
    return {"tags": list(by_tag), "n_tags": len(by_tag), "task_runs": len(runs), "solvable_runs": len(solv),
            "calls": calls, "malformed_calls": bad, "malformed_rate": round(bad / calls, 6) if calls else 0.0,
            "resolved_runs": len(solv) - len(unres), "resolved_min": min(resolved), "resolved_max": max(resolved),
            "rank1_runs": rank1, "rank1_rate": round(rank1 / len(solv), 6),
            "unresolved_runs": len(unres), "unresolved": {c: cats.get(c, 0) for c in CATEGORIES[2:]},
            "unresolved_right_file": sum(cats.get(c, 0) for c in CATEGORIES if c.startswith("RIGHT_FILE")),
            "unresolved_no_edit": cats.get("NO_EDIT", 0) + cats.get("NO_EDIT_TOOL", 0),
            "wrong_file_share": round(cats.get("WRONG_FILE", 0) / max(1, len(unres)), 6),
            "right_file_share": round(sum(cats.get(c, 0) for c in CATEGORIES if c.startswith("RIGHT_FILE"))
                                      / max(1, len(unres)), 6),
            "tools": {n: {"calls": c, "malformed": b, "rate": round(b / c, 6) if c else 0.0}
                      for n, (c, b) in sorted(tools.items())}}


def _repo(task_id: str) -> str:
    return task_id.rsplit("_", 1)[0]


def stability(by_tag: dict) -> dict:
    """Does a task's outcome depend on the configuration? Over every run (all tags and panel designs) in which the
    task's reference patch resolves, a task is "always" or "never" resolved, or "mixed"; tasks with one such run are
    left out."""
    outcomes: dict[str, list[bool]] = {}
    for t in by_tag.values():
        for tid, v in t["per_task"].items():
            if v["category"] != "GOLD_UNSOLVABLE":
                outcomes.setdefault(tid, []).append(v["category"] == "RESOLVED")
    kind = {tid: "always" if all(o) else "never" if not any(o) else "mixed" for tid, o in outcomes.items() if len(o) >= 2}
    n = Counter(kind.values())
    return {"tags": list(by_tag), "n_runs": len(by_tag), "tasks": len(kind),
            "runs_per_task_min": min((len(outcomes[t]) for t in kind), default=0),
            "runs_per_task_max": max((len(outcomes[t]) for t in kind), default=0),
            **{k: n.get(k, 0) for k in ("always", "never", "mixed")},
            "mixed_share": round(n.get("mixed", 0) / max(1, len(kind)), 6),
            "mixed_tasks": sorted(t for t, k in kind.items() if k == "mixed"),
            "by_repo": {r: {k: sum(1 for t, kt in kind.items() if _repo(t) == r and kt == k) for k in ("always", "never", "mixed")}
                        for r in sorted({_repo(t) for t in kind})}}


def by_repo(by_tag: dict) -> dict:
    """Resolved and gold-solvable task counts per repository, for panels that mix repositories."""
    out = {}
    for tag, t in by_tag.items():
        repos: dict[str, list[int]] = {}
        for tid, v in t["per_task"].items():
            r = repos.setdefault(_repo(tid), [0, 0])
            if v["category"] != "GOLD_UNSOLVABLE":
                r[0], r[1] = r[0] + (v["category"] == "RESOLVED"), r[1] + 1
        if len(repos) > 1:
            out[tag] = {r: {"resolved": a, "solvable": b} for r, (a, b) in sorted(repos.items())}
    return out


def build(by_tag: dict) -> dict:
    eras = {name: aggregate({t: by_tag[t] for t in tags if t in by_tag})
            for name, tags in ERAS.items() if any(t in by_tag for t in tags)}
    return {"by_tag": by_tag, "aggregate": eras.get("edit_file") or aggregate(by_tag), "eras": eras,
            "excluded": {t: why for t, why in EXCLUDED.items() if t in by_tag}, "stability": stability(by_tag),
            "by_repo": by_repo({t: v for t, v in by_tag.items() if t not in EXCLUDED})}


def _tag_key(tag: str) -> tuple:
    return (tag[:1], int(tag[1:]) if tag[1:].isdigit() else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "failure_audit.json")
    a = ap.parse_args()
    tags = a.tags or sorted((p.name.removeprefix("kaggle_eval_") for p in (ROOT / "results").glob("kaggle_eval_*")
                             if (p / "agent_eval" / "per_task.jsonl").exists()), key=_tag_key)
    golds = {t["instance_id"]: gold_files(t["patch"]) for t in
             map(json.loads, (ROOT / "data" / "tasks.jsonl").read_text(encoding="utf-8").splitlines())}
    out = {t: audit(t, golds) for t in tags}
    a.out.write_bytes((json.dumps(build(out), indent=1) + "\n").encode("utf-8"))
    ids = sorted(set().union(*(t["per_task"] for t in out.values())))
    short = {"GOLD_UNSOLVABLE": "--", "RESOLVED": "OK", "NO_EDIT_TOOL": "NT", "NO_EDIT": "NE", "WRONG_FILE": "WF", "RIGHT_FILE_TOOL": "RT",
             "RIGHT_FILE_TIMEOUT": "TO", "RIGHT_FILE_WRONG_FIX": "WX"}
    print("task       " + " ".join(f"{t:>3}" for t in tags))
    for i in ids:
        print(f"{i:10} " + " ".join(f"{short[out[t]['per_task'][i]['category']]:>3}" if i in out[t]["per_task"] else "  ?"
                                    for t in tags))
    for t in tags:
        print(t, out[t]["counts"])


if __name__ == "__main__":
    main()
