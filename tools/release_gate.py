"""Release gate: may a frozen candidate be submitted, and on what evidence?

    python tools/release_gate.py --tag S14 --base S12          # write candidates/S14/GATE.json
    python tools/release_gate.py --sanity S12                    # print a tag's dev-panel SANITY check

A tag with its own dev panel is judged by that panel (panel_sanity). A tag without one (GPU quota exhausted; owner
decision 2026-10-27: one new, improved version every day even without a panel) needs a passing GATE.json, which
requires all of:
  1. the candidate rebuilds to the zip sha recorded at freeze, and the grader's own libraries compile it;
  2. its base tag passed panel SANITY (>= 20 tasks finished, resolved_on_solvable >= 4, 120 x mean task time
     <= 11 h, editor never missing after a localize call), so the time profile it inherits was measured;
  3. agent.yaml, eval_config.yaml and configs/sampling.yaml are byte-identical to the base's (budget, model,
     sampling and tools unchanged: no unmeasured effect on the 12 h limit);
  4. every skill file equals the files of one fully passing harness-sandbox check (kernels/editor_check, its
     summary records the sha256 of the scripts it ran);
  5. the prompt changes at most PROMPT_MAX_CHANGED_LINES lines unless --allow-prompt-change is given (S13: a
     plausible 2-line prompt rule fixed nothing and made sessions slower; prompt edits need a panel);
  6. agent/ equals the candidate and both test suites pass (repo Python and the grader's third_party/venv).
tools/kaggle_submit.py refuses a panel-less tag without a passing GATE.json for the same zip sha.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import build_submission as bs  # noqa: E402

SAME_AS_BASE = ("agent.yaml", "eval_config.yaml", "configs/sampling.yaml")
SKILL_FILES = ("skills/swe/scripts/localize.py", "skills/swe/scripts/finalize.py", "skills/swe/scripts/edit.py",
               "skills/swe/SKILL.md")
PROMPT = "prompts/system.md"
PROMPT_MAX_CHANGED_LINES = 6
LIMIT_H, MIN_FINISHED, MIN_RESOLVED = 11.0, 20, 4


def sha(p: Path) -> str:
    data = p.read_bytes()
    if p.suffix.lower() in bs.TEXT_EXT:  # the zip stores LF; compare what is shipped
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def editor_missing_after_localize(traces: Path) -> list[str]:
    hits = []
    for f in sorted(traces.glob("trace_*.json")):
        loc = False
        for st in json.loads(f.read_text(encoding="utf-8")).get("steps", []):
            obs = json.dumps(st.get("observation") or "")
            for tc in st.get("tool_calls") or []:
                a = tc.get("arguments") or {}
                if tc.get("function_name") == "run_skill_script" and "localize" in json.dumps(a):
                    loc = True
                elif (tc.get("function_name") == "run_command" and "edit.py" in str(a.get("command", "")) and loc
                      and ("can't open file" in obs or "No such file or directory" in obs)):
                    hits.append(f.stem.removeprefix("trace_"))
    return hits


def panel_sanity(tag: str) -> dict:
    d = ROOT / "results" / f"kaggle_eval_{tag}" / "agent_eval"
    if not (d / "per_task.jsonl").exists():
        return {"tag": tag, "panel": False, "passed": False, "why": "no dev panel"}
    rows = [json.loads(l) for l in (d / "per_task.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    done = [r for r in rows if r["agent"].get("duration_s")]
    resolved = sum(bool(r["agent"].get("resolved")) and bool(r["gold"].get("resolved")) for r in rows)
    hours = 120 * statistics.mean(r["agent"]["duration_s"] for r in done) / 3600 if done else float("inf")
    missing = editor_missing_after_localize(d / "results" / "traces")
    checks = {"finished": len(done) >= MIN_FINISHED, "resolved_on_solvable": resolved >= MIN_RESOLVED,
              "hours_120": hours <= LIMIT_H, "editor_missing_after_localize": not missing}
    return {"tag": tag, "panel": True, "n": len(rows), "finished": len(done), "resolved_on_solvable": resolved,
            "hours_120": round(hours, 2), "editor_missing_after_localize": missing, "checks": checks,
            "passed": all(checks.values())}


def passing_editor_checks() -> list[tuple[str, dict]]:
    out = []
    for f in sorted((ROOT / "results" / "editor_check").glob("*/editor_check.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        if s.get("sha256") and s.get("total") and s.get("passed") == s.get("total"):
            out.append((f.parent.name, s["sha256"]))
    return out


def run_tests() -> dict:
    env_py = ROOT / "third_party" / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    res = {}
    for name, cmd in (("repo", [sys.executable, "-m", "pytest", "-q", "tests/"]),
                      ("grader_venv", [str(env_py), "-m", "pytest", "-q", "tests/test_agent.py"])):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1200,
                           env={**os.environ, "PYTHONUTF8": "1"})
        res[name] = {"returncode": r.returncode, "tail": (r.stdout + r.stderr).strip().splitlines()[-1:]}
    return res


def gate(tag: str, base: str, allow_prompt_change: bool) -> dict:
    cand, basedir = bs.CANDIDATES / tag, bs.CANDIDATES / base
    man = json.loads((cand / "MANIFEST.json").read_text(encoding="utf-8"))
    checks, notes = {}, {}
    with tempfile.TemporaryDirectory() as td:
        staged = bs.stage(cand / "bundle", Path(td) / "s")
        bs.validate(staged)
        got = hashlib.sha256(bs.build_zip(staged)).hexdigest()
        checks["rebuilds_to_frozen_sha"] = got == man["zip_sha256"]
        try:
            notes["official"] = bs.official_check(staged)
            checks["official_compile"] = notes["official"].startswith("compiled:")
        except bs.BundleError as e:
            notes["official"], checks["official_compile"] = str(e)[:500], False
    notes["base_sanity"] = panel_sanity(base)
    checks["base_passed_panel_sanity"] = notes["base_sanity"]["passed"]
    checks["budget_model_sampling_tools_same_as_base"] = all(
        sha(cand / "bundle" / f) == sha(basedir / "bundle" / f) for f in SAME_AS_BASE)
    files = {f: sha(cand / "bundle" / f) for f in SKILL_FILES}
    matching = [v for v, shas in passing_editor_checks() if all(shas.get(f) == h for f, h in files.items())]
    notes["harness_sandbox_check"] = matching or "no fully passing kernels/editor_check run used these exact skill files"
    checks["skills_passed_harness_sandbox_check"] = bool(matching)
    old = (basedir / "bundle" / PROMPT).read_text(encoding="utf-8").splitlines()
    new = (cand / "bundle" / PROMPT).read_text(encoding="utf-8").splitlines()
    changed = sum(1 for l in difflib.unified_diff(old, new, lineterm="", n=0)
                  if l[:1] in "+-" and not l.startswith(("+++", "---")))
    notes["prompt_changed_lines"] = changed
    checks["prompt_change_small_or_allowed"] = changed <= PROMPT_MAX_CHANGED_LINES or allow_prompt_change
    notes["changed_files_vs_base"] = sorted(
        str(p.relative_to(cand / "bundle")).replace("\\", "/") for p in (cand / "bundle").rglob("*") if p.is_file()
        and (not (basedir / "bundle" / p.relative_to(cand / "bundle")).exists()
             or sha(p) != sha(basedir / "bundle" / p.relative_to(cand / "bundle"))))
    agent_files = {str(p.relative_to(ROOT / "agent")).replace("\\", "/"): sha(p) for p in (ROOT / "agent").rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts}
    cand_files = {str(p.relative_to(cand / "bundle")).replace("\\", "/"): sha(p) for p in (cand / "bundle").rglob("*")
                  if p.is_file()}
    checks["agent_dir_equals_candidate"] = agent_files == cand_files
    if checks["agent_dir_equals_candidate"]:
        notes["tests"] = run_tests()
        checks["tests_pass"] = all(v["returncode"] == 0 for v in notes["tests"].values())
    else:
        checks["tests_pass"] = False
        notes["tests"] = "not run: agent/ differs from the candidate, so the tests would not test what ships"
    return {"tag": tag, "base": base, "zip_sha256": man["zip_sha256"], "checks": checks, "notes": notes,
            "allow_prompt_change": allow_prompt_change, "passed": all(checks.values()),
            "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}


def submittable(tag: str, zip_sha: str) -> tuple[bool, str]:
    """Used by tools/kaggle_submit.py: own panel decides; without a panel a passing GATE.json for this sha."""
    ps = panel_sanity(tag)
    if ps["panel"]:
        return ps["passed"], f"own dev panel SANITY {'passed' if ps['passed'] else 'FAILED'}: {ps.get('checks')}"
    g = bs.CANDIDATES / tag / "GATE.json"
    if not g.exists():
        return False, "no dev panel and no GATE.json (python tools/release_gate.py --tag ... --base ...)"
    gj = json.loads(g.read_text(encoding="utf-8"))
    ok = gj.get("passed") is True and gj.get("zip_sha256") == zip_sha
    return ok, f"GATE.json passed={gj.get('passed')} sha_match={gj.get('zip_sha256') == zip_sha} base={gj.get('base')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag")
    ap.add_argument("--base")
    ap.add_argument("--allow-prompt-change", action="store_true")
    ap.add_argument("--sanity", metavar="TAG")
    a = ap.parse_args()
    if a.sanity:
        print(json.dumps(panel_sanity(a.sanity), indent=1))
        return 0
    if not (a.tag and a.base):
        ap.error("--tag and --base are required")
    res = gate(a.tag, a.base, a.allow_prompt_change)
    (bs.CANDIDATES / a.tag / "GATE.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: res[k] for k in ("tag", "base", "passed", "checks")}, indent=1))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
