#!/usr/bin/env python3
"""Patch hygiene before submit_patch. Stdlib only. Safe: never touches .git, never deletes tracked files.

1. Reverts edits to protected files the grader resets anyway (tests, conftest.py, pytest.ini, pyproject.toml,
   setup.cfg, tox.ini, ...), so they cannot conflict with the hidden test patch.
2. Deletes untracked scratch files the agent left in the workspace (repro/debug scripts, *.orig/*.rej, new test
   files); other untracked files (e.g. a new source module) are kept and listed.
3. Byte-compiles every changed .py file and reports syntax errors (exit 1) so they are fixed before submitting.
4. Imports every changed package module in a fresh interpreter and reports import-time errors whose traceback
   passes through a changed file (exit 1): a patch that compiles can still break the import (S13 panel,
   rich_4070: a removed `import inspect` still used in a class body -> NameError, every hidden test failed).
5. Prints the resulting `git diff --stat`; warns when the patch is empty.

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


# ---- editor install (kept identical in localize.py and finalize.py; a test checks parity) ----
TOOLS_DIR = os.environ.get("SWE_TOOLS_DIR")  # tests only; the default is the workspace's .git directory
EDITOR_CMD = "/workspace/.git/swe/edit.py"


def install_editor(root: str) -> str:
    """Copy the sibling edit.py (materialized next to this script by run_skill_script) to <workspace>/.git/swe/,
    where run_command can call it after this script's temporary directory is gone. Commands spell it
    /workspace/.git/swe/edit.py: the harness rewrites /workspace and /tmp inside run_command strings to the task
    sandbox but not inside this Python process, so a /tmp install is invisible to run_command (S6 dev panel: the
    editor was not found in most tasks). Files under .git never enter the patch. Returns the status line to print."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "edit.py"), "rb") as fh:
            data = fh.read()
    except OSError as e:
        return f"EDITOR NOT INSTALLED ({type(e).__name__}); run this script once more."
    d = TOOLS_DIR or os.path.join(root, ".git", "swe")
    dst = os.path.join(d, "edit.py")
    try:
        os.makedirs(d, exist_ok=True)
        old = None
        if os.path.isfile(dst):
            with open(dst, "rb") as fh:
                old = fh.read()
        if old != data:
            tmp = f"{dst}.{os.getpid()}.tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dst)
    except OSError as e:
        return f"EDITOR NOT INSTALLED ({type(e).__name__}: {e}); run this script once more."
    in_workspace = not TOOLS_DIR and os.path.basename(os.path.normpath(root)) == "workspace"
    return f"EDITOR READY: python3 {EDITOR_CMD if in_workspace else dst.replace(os.sep, '/')}"



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


IMPORT_TIMEOUT_S = 30
IMPORT_MAX_MODULES = 6


def importable(root: str, path: str) -> str | None:
    """Dotted module name for a changed file inside a package (a top-level directory with __init__.py, or
    docs_src/, whose tutorials the tests import); None for scripts and other loose files, which may run code."""
    parts = path[:-3].split("/")
    if parts[0] == "src" and len(parts) > 2:
        parts = parts[1:]
        root = os.path.join(root, "src")
    if len(parts) < 2 or not all(p.isidentifier() for p in parts):
        return None
    if parts[0] != "docs_src" and not os.path.isfile(os.path.join(root, parts[0], "__init__.py")):
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def import_errors(root: str, changed_py: list[str]) -> tuple[list[str], list[str]]:
    """(errors caused by the change, other import failures) for up to IMPORT_MAX_MODULES changed modules."""
    caused, other = [], []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # no __pycache__ in the workspace
    mods = [(p, m) for p in changed_py if (m := importable(root, p))][:IMPORT_MAX_MODULES]
    for path, mod in mods:
        cwd = os.path.join(root, "src") if path.startswith("src/") else root
        try:
            r = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=cwd, env=env, capture_output=True,
                               text=True, timeout=IMPORT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            other.append(f"{mod}: import took over {IMPORT_TIMEOUT_S}s (not checked)")
            continue
        if r.returncode == 0:
            continue
        lines = r.stderr.strip().splitlines()
        tail = "\n    ".join(lines[-6:])
        missing = re.match(r"ModuleNotFoundError: No module named '([\w.]+)'", lines[-1] if lines else "")
        external = bool(missing) and not os.path.isdir(os.path.join(cwd, missing.group(1).split(".")[0]))
        # blame the change only when the traceback runs through a changed file and is not a missing third-party
        # package (an environment gap the hidden-test run does not have); otherwise it may be pre-existing
        through = any(p in r.stderr.replace(os.sep, "/") for p, _ in mods)
        (caused if through and not external else other).append(f"import {mod}:\n    {tail}")
    return caused, other


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
    broken, other = import_errors(root, changed_py) if not errors else ([], [])
    stat = git(root, "diff", "HEAD", "--stat").strip()
    print("\n".join(msgs) if msgs else "workspace clean: no protected or scratch files touched")
    if errors:
        print("SYNTAX ERRORS - fix these before submit_patch:\n  " + "\n  ".join(errors))
    if broken:
        print("IMPORT ERRORS caused by your change - every hidden test fails until you fix them:\n  " + "\n  ".join(broken))
        errors += broken
    if other:
        print("note: import failures that do not run through your changed files (probably pre-existing):\n  "
              + "\n  ".join(other))
    if not stat and not kept_new:
        print("WARNING: the patch is EMPTY. Make the source change before calling submit_patch.\n" + install_editor(root))
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
