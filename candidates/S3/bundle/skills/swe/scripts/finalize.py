#!/usr/bin/env python3
"""Patch hygiene before submit_patch. Stdlib only. Safe: never touches .git, never deletes tracked files.

1. Reverts edits to protected files the grader resets anyway (tests, conftest.py, pytest.ini, pyproject.toml,
   setup.cfg, tox.ini, ...), so they cannot conflict with the hidden test patch.
2. Deletes untracked scratch files the agent left in the workspace (repro/debug scripts, *.orig/*.rej, new test
   files); other untracked files (e.g. a new source module) are kept and listed.
3. Byte-compiles every changed .py file and reports syntax errors (exit 1) so they are fixed before submitting.
4. Prints the resulting `git diff --stat`; warns when the patch is empty.

Usage: run_skill_script(skill_name="swe", file_path="scripts/finalize.py")   [--dry-run to only report]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

PROTECTED = re.compile(r"(^|/)(tests?|testing)/.*\.py$|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)(conftest\.py|pytest\.ini|"
                       r"\.pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|sitecustomize\.py|usercustomize\.py|"
                       r"_swegemma_stubs\.py)$|\.pth$")
# generic scratch names only at the repository root (a new module inside a package is never deleted), plus
# anything under a new top-level tmp/ (write_file("/tmp/x.py") lands in /workspace/tmp/x.py)
SCRATCH = re.compile(r"^(repro\w*|reproduce\w*|debug\w*|scratch\w*|tmp\w*|temp\w*|check_\w+|verify\w*|try_\w+|nohup)"
                     r"\.(py|sh|txt|log|out)$|\.(orig|rej|bak|swp)$|^tmp/")


def find_root() -> str:
    cands = [os.environ.get("SWE_WORKSPACE"), os.environ.get("PWD"),
             *os.environ.get("PYTHONPATH", "").split(os.pathsep), "/workspace"]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return os.path.realpath(c)
    return "/workspace"


def git(root: str, *args: str, check: bool = False) -> str:
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def status(root: str) -> list[tuple[str, str]]:
    """(code, path) from porcelain v1 -z; renames report the new path."""
    out = git(root, "status", "--porcelain", "-z", "--untracked-files=all", check=True)
    items, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        if len(e) >= 4:
            code, path = e[:2], e[3:]
            items.append((code, path))
            if code[0] in "RC":
                i += 1  # skip the rename source
        i += 1
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=None)
    a, _ = ap.parse_known_args(argv)
    root = os.path.realpath(a.root) if a.root else find_root()
    if not os.path.isdir(os.path.join(root, ".git")):
        print(f"ERROR: no git workspace at {root}")
        return 2
    msgs, reverted, deleted, kept_new, changed_py = [], [], [], [], []
    for code, path in status(root):
        untracked = code == "??"
        if path.startswith(".git/"):
            continue
        if PROTECTED.search(path):
            if untracked:
                deleted.append(path)
                if not a.dry_run:
                    os.remove(os.path.join(root, path))
            else:
                reverted.append(path)
                if not a.dry_run:
                    git(root, "checkout", "HEAD", "--", path)
            continue
        if untracked and SCRATCH.search(path):
            deleted.append(path)
            if not a.dry_run:
                os.remove(os.path.join(root, path))
            continue
        if untracked:
            kept_new.append(path)
        if path.endswith(".py") and code.strip() != "D" and os.path.isfile(os.path.join(root, path)):
            changed_py.append(path)
    if reverted:
        msgs.append("reverted protected files (the grader resets them anyway): " + ", ".join(reverted))
    if deleted:
        msgs.append(("would delete" if a.dry_run else "deleted") + " scratch/test files: " + ", ".join(deleted))
    if kept_new:
        msgs.append("NEW untracked files kept in the patch (delete them if they are not part of the fix): " + ", ".join(kept_new))
    errors = []
    for path in changed_py:
        try:  # compile() in memory: no .pyc is written into the workspace
            with open(os.path.join(root, path), "rb") as fh:
                compile(fh.read(), path, "exec", dont_inherit=True)
        except SyntaxError as e:
            errors.append(f"{path}:{e.lineno}: {e.msg} -> {(e.text or '').strip()[:120]}")
        except Exception as e:  # unreadable file, null bytes, ...
            errors.append(f"{path}: {type(e).__name__}: {e}")
    stat = git(root, "diff", "HEAD", "--stat").strip()
    print("\n".join(msgs) if msgs else "workspace clean: no protected or scratch files touched")
    if errors:
        print("SYNTAX ERRORS - fix these before submit_patch:\n  " + "\n  ".join(errors))
    if not stat and not kept_new:
        print("WARNING: the patch is EMPTY. Make the source change before calling submit_patch.")
    else:
        print("PATCH:\n" + (stat or "(only new files)"))
    if not errors and (stat or kept_new):
        print("OK: call submit_patch now.")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"finalize failed ({type(e).__name__}: {e}); check git status and git diff --stat with run_command, then submit_patch.")
        sys.exit(0)
