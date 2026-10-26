#!/usr/bin/env python3
"""Replace a line range of a source file with the text of a scratch file written by write_file. Stdlib only.

Fallback for edit_file: a call carrying two long code values (old_string, new_string) can lose the second one in
the tool-call serialization (S4 dev panel: 41 edit_file calls lost old_string in 7 tasks, then were resent
unchanged); write_file carries a single code value and this script takes only a path and two numbers.

  1. write_file(filepath="tmp_new_lines.txt", content="<replacement lines, exact indentation>")
  2. run_skill_script(skill_name="swe", file_path="scripts/replace_lines.py",
                      args={"file": "pkg/mod.py", "start": 10, "end": 12})

Lines start..end (1-based, inclusive) are replaced; end = start - 1 inserts before line start. A Python file that
would no longer compile is left unchanged and the scratch file is kept, so only the numbers or the text need fixing.
Otherwise the scratch file is deleted (finalize.py deletes it too) and the changed region is printed.
"""
from __future__ import annotations

import argparse
import os
import sys

SCRATCH = "tmp_new_lines.txt"
CONTEXT = 2
MAX_SHOWN = 60
TOKEN_LEAK = '<|"|>'  # string delimiter of the model's call format, sometimes left at the end of a value
EOLS = "\r\n"


def find_root() -> str:
    cands = [os.environ.get("SWE_WORKSPACE"), os.environ.get("PWD"),
             *os.environ.get("PYTHONPATH", "").split(os.pathsep), "/workspace"]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return os.path.realpath(c)
    return "/workspace"


def inside(root: str, rel: str) -> str | None:
    rel = rel.strip().lstrip("/")
    rel = rel[len("workspace/"):] if rel.startswith("workspace/") else rel  # absolute /workspace/... paths
    p = os.path.realpath(os.path.join(root, rel))
    return p if p == root or p.startswith(root + os.sep) else None


def show(lines: list[str], lo: int, hi: int) -> str:
    """Numbered lines lo..hi (1-based, clipped), truncated in the middle when long."""
    lo, hi = max(1, lo), min(len(lines), hi)
    nums = list(range(lo, hi + 1))
    if len(nums) > MAX_SHOWN:
        nums = nums[:MAX_SHOWN // 2] + [0] + nums[-MAX_SHOWN // 2:]
    return "\n".join("     ..." if n == 0 else f"{n:6d}  {lines[n - 1].rstrip(EOLS)}" for n in nums)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--src", default=SCRATCH)
    ap.add_argument("--root", default=None)
    a, _ = ap.parse_known_args(argv)
    usage = ('pass args={"file": "path/to/module.py", "start": FIRST_LINE, "end": LAST_LINE} after writing the '
             f"replacement lines with write_file to {SCRATCH}")
    root = os.path.realpath(a.root) if a.root else find_root()
    try:
        start, end = int(str(a.start).strip()), int(str(a.end).strip())
    except ValueError:
        print(f"ERROR: start and end must be line numbers; {usage}")
        return 2
    target, src = inside(root, a.file) if a.file.strip() else None, inside(root, a.src)
    if not target or not os.path.isfile(target):
        print(f"ERROR: no file {a.file!r} in the workspace; {usage} (for a new file use write_file)")
        return 2
    if not src or not os.path.isfile(src):
        print(f"ERROR: {a.src} not found; first call write_file with filepath {SCRATCH} and the new lines as content")
        return 2
    with open(target, encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines(keepends=True)
    if not (1 <= start <= len(lines) + 1 and start - 1 <= end <= len(lines)):
        print(f"ERROR: lines {start}-{end} are outside {a.file} (1-{len(lines)}); end = start - 1 inserts before start")
        return 2
    with open(src, encoding="utf-8", newline="") as fh:
        text = fh.read()
    text = text.rstrip(EOLS)
    if text.endswith(TOKEN_LEAK):
        text = text[:-len(TOKEN_LEAK)].rstrip(EOLS)
    eol = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    new = [ln + eol for ln in text.splitlines()]
    old = lines[start - 1:end]
    out = lines[:start - 1] + new + lines[end:]
    if target.endswith(".py"):
        try:
            compile("".join(out), a.file, "exec", dont_inherit=True)
        except SyntaxError as e:
            print(f"NOT APPLIED: the result would not compile ({e.msg} at line {e.lineno}); {a.file} is unchanged and "
                  f"{a.src} is kept. Lines {start}-{end} now:\n{show(lines, start, end)}\n"
                  "Fix the line numbers or rewrite the scratch file, then run this script again.")
            return 1
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out))
    os.remove(src)
    lo, hi = max(1, start - CONTEXT), min(len(out), start + len(new) - 1 + CONTEXT)
    print(f"OK: {a.file} lines {start}-{end} ({len(old)} lines) replaced by {len(new)} lines.\nREMOVED:\n"
          f"{show(lines, start, end) if old else '      (nothing, insertion)'}\nNOW (lines {lo}-{hi}):\n{show(out, lo, hi)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"replace_lines failed ({type(e).__name__}: {e}); retry edit_file with a shorter old_string of 1 to 3 lines.")
        sys.exit(0)
