"""Per-task failure taxonomy of dev-panel runs: where along issue -> localization -> edit -> patch each task was lost.

    python -m analysis.failure_audit [--tags S1 S2 S3 S4] [--out results/failure_audit.json]

Inputs: results/kaggle_eval_<tag>/agent_eval/{per_task.jsonl, results/traces/*.json} and the gold patches in
data/tasks.jsonl (read locally, never copied: the output keeps task ids, file-level booleans and counts only).

Categories, first match wins (denominator = all panel tasks; "solvable" = the gold patch resolves the task):
  GOLD_UNSOLVABLE      the reference patch itself fails in the panel environment
  RESOLVED             hidden tests pass
  NO_EDIT_TOOL         no successful write to a non-test source file, >= 2 edit attempts failed at the tool level
                       (a malformed call, or from S6 the heredoc editor refusing the block)
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
    for s in trace["steps"]:
        obs = (s.get("observation") or {}).get("content", "")
        for tc in s.get("tool_calls") or []:
            name, a = tc["function_name"], tc["arguments"]
            editor = name == "run_command" and EDITOR_CMD.search(str(a.get("command", "")))
            is_edit = name in ("edit_file", "write_file") or bool(editor)
            edits += is_edit
            if malformed(name, a):
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
                elif "EDIT NOT APPLIED" in obs:
                    bad_edits += 1
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
            "localize_gold_file_rank": rank}


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
            "malformed_edits": 0, "localize_gold_file_rank": None}
        per[r["id"]] = {"category": classify(r, f), **f}
    counts = Counter(v["category"] for v in per.values())
    return {"counts": {c: counts.get(c, 0) for c in CATEGORIES}, "per_task": per}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "failure_audit.json")
    a = ap.parse_args()
    tags = a.tags or sorted((p.name.removeprefix("kaggle_eval_") for p in (ROOT / "results").glob("kaggle_eval_S*")
                             if (p / "agent_eval" / "per_task.jsonl").exists()), key=lambda t: int(t[1:]))
    golds = {t["instance_id"]: gold_files(t["patch"]) for t in
             map(json.loads, (ROOT / "data" / "tasks.jsonl").read_text(encoding="utf-8").splitlines())}
    out = {t: audit(t, golds) for t in tags}
    a.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    ids = sorted(next(iter(out.values()))["per_task"])
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
