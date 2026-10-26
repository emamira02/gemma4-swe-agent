#!/usr/bin/env python3
"""Edit one workspace file from run_command: SEARCH/REPLACE blocks or a line range, text on stdin. Stdlib only.

Why this channel: the model's tool-call format closes every string value with a dedicated token and its keys come
out in alphabetical order, so in edit_file the long new_string precedes old_string. When the model closes new_string
with a stray backtick instead, old_string is swallowed (S4 dev panel: 41 of 78 edit_file calls malformed; two
solvable tasks ended with no edit at all). run_command carries a single value (0 malformed calls in 807 over
S1-S4) and a quoted heredoc passes code verbatim, without any escaping.

  python3 /tmp/swe/edit.py path/to/module.py <<'EOF'
  <<<<<<< SEARCH
  exact current lines
  =======
  replacement lines
  >>>>>>> REPLACE
  EOF

  Several blocks may follow each other: they apply in order, all or nothing.
  python3 /tmp/swe/edit.py path/to/module.py 120-125 <<'EOF'   replace lines 120..125 by stdin (120-119 inserts)
  python3 /tmp/swe/edit.py path/to/new_module.py <<'EOF'       new file: stdin (or the REPLACE part) is its content

Matching: exact, then ignoring trailing whitespace and surrounding blank lines, then ignoring a uniform indentation
offset (the replacement is shifted by the same offset). A SEARCH that is missing or ambiguous changes nothing and
prints the closest region with line numbers; resending a block this editor already applied is reported, not redone. A
Python result that does not compile is not written. Writes are atomic and keep line endings, final newline and file
mode. Tests and test configuration are refused (the grader resets them). Exit 0 = applied, 1 = nothing written.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sys
import tempfile

EDITOR = os.path.abspath(__file__).replace(os.sep, "/")  # /tmp/swe/edit.py once installed by localize.py
PROTECTED = re.compile(r"(^|/)(tests?|testing)/.*\.py$|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)(conftest\.py|pytest\.ini|"
                       r"\.pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|sitecustomize\.py|usercustomize\.py|"
                       r"_swegemma_stubs\.py)$|\.pth$")  # identical to finalize.py (a test checks parity)
SEARCH_RX = re.compile(r"^\s*<{5,9}\s*SEARCH\s*$")
DIVIDER_RX = re.compile(r"^\s*={5,9}\s*$")
REPLACE_RX = re.compile(r"^\s*>{5,9}\s*REPLACE\s*$")
RANGE_RX = re.compile(r"^(\d+)(?:\s*[-:,]\s*(\d+))?$")
TERMINATOR_RX = re.compile(r"^\s*EOF\W*$")  # a heredoc end line left in the text when the call was cut short
NUMBERED_RX = re.compile(r"^\s{0,5}\d{1,6}  (.*)$")  # a line copied with the number this editor prints
TOKEN_LEAK = '<|"|>'
JOURNAL = os.path.join(".git", "swe_edit_journal")  # blocks applied in this workspace; git diff ignores .git
MAX_SHOWN, CONTEXT, MAX_OUT = 40, 2, 3800
TEMPLATE = (f"python3 {EDITOR} path/to/file.py <<'EOF'\n<<<<<<< SEARCH\nexact current lines\n=======\n"
            "replacement lines\n>>>>>>> REPLACE\nEOF")


class EditError(Exception):
    """Nothing is written; the message tells the model what to change."""


# ---------- workspace and input ----------
def find_root() -> str:
    for c in (os.environ.get("SWE_WORKSPACE"), os.getcwd(), os.environ.get("PWD"), "/workspace"):
        if c and os.path.isdir(os.path.join(c, ".git")):
            return os.path.realpath(c)
    return os.path.realpath(os.getcwd())


def resolve(root: str, path: str) -> tuple[str, str]:
    """(absolute, workspace-relative) path, symlinks resolved; anything outside the workspace is refused."""
    p = path.strip().strip("'\"")
    if p.startswith("/workspace/") and not root.startswith("/workspace"):
        p = p[len("/workspace/"):]
    full = os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p))
    if full != root and not full.startswith(root + os.sep):
        raise EditError(f"{path} is outside the workspace {root}; give a path relative to the repository root.")
    rel = os.path.relpath(full, root).replace(os.sep, "/")
    if PROTECTED.search(rel):
        raise EditError(f"{rel} is a test or test-configuration file: the grader resets those, so change the source "
                        "code instead.")
    return full, rel


def _ancestor_scripts(max_depth: int = 4) -> list[bytes]:
    """Command lines of the shells/timeout above this process (Linux /proc only)."""
    out, pid = [], os.getppid()
    for _ in range(max_depth):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                out.extend(fh.read().split(b"\0"))
            with open(f"/proc/{pid}/stat", "rb") as fh:
                pid = int(fh.read().rsplit(b")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if pid <= 1:
            break
    return out


def unquoted_heredoc_body(scripts: list[bytes] | None = None) -> str | None:
    """With <<EOF (unquoted) bash has already expanded $, backticks and backslashes in stdin; recover the raw text
    from the shell's own command line (nearest ancestor first, which holds the command exactly as sent). None when
    the heredoc was quoted, the command line is unavailable or it runs the editor more than once."""
    for script in _ancestor_scripts() if scripts is None else scripts:
        ms = list(re.finditer(rb"edit\.py[^\n]*?<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2[^\n]*\n", script))
        if not ms:
            continue
        m = ms[0]
        if m.group(2) or len(ms) > 1:
            return None
        tag, body = m.group(3), script[m.end():]
        end = re.search(rb"^\t*" + re.escape(tag) + rb"[ \t]*$", body, re.M)
        raw = body[:end.start()] if end else body
        if m.group(1):
            raw = re.sub(rb"(?m)^\t+", b"", raw)
        return raw.decode("utf-8", "surrogateescape")
    return None


def read_payload() -> str:
    raw = unquoted_heredoc_body()
    if raw is None:
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
    return raw.replace("\r\n", "\n").replace(TOKEN_LEAK, "")


def clean_tail(lines: list[str]) -> list[str]:
    """Drop the empty item left by the heredoc's final newline and a heredoc end line swallowed into the text when
    the call was cut short; other blank lines are content."""
    lines = list(lines)
    for _ in range(2):
        if lines and lines[-1] == "":
            lines.pop()
        if lines and TERMINATOR_RX.match(lines[-1]):
            lines.pop()
    return lines


# ---------- blocks and matching ----------
def parse_blocks(text: str) -> list[tuple[list[str], list[int]]]:
    """[(lines between the SEARCH and REPLACE markers, positions of divider lines among them)]. Every divider is a
    candidate split, so code that itself contains a line of = signs still parses (see _locate)."""
    lines, blocks, i = text.split("\n"), [], 0
    while i < len(lines):
        if not SEARCH_RX.match(lines[i]):
            if REPLACE_RX.match(lines[i]) or DIVIDER_RX.match(lines[i]) and not blocks:
                raise EditError(f"line {i + 1} of the edit text: a marker without a preceding <<<<<<< SEARCH line.")
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not REPLACE_RX.match(lines[j]) and not SEARCH_RX.match(lines[j]):
            j += 1
        body = lines[i + 1:j]
        divs = [k for k, ln in enumerate(body) if DIVIDER_RX.match(ln)]
        if j >= len(lines) or not REPLACE_RX.match(lines[j]) or not divs:
            raise EditError(f"block {len(blocks) + 1} is incomplete: each block needs the three marker lines "
                            "<<<<<<< SEARCH, ======= and >>>>>>> REPLACE, each on its own line.")
        blocks.append((body, divs))
        i = j + 1
    return blocks


def _strip_blank_edges(lines: list[str]) -> list[str]:
    a, b = 0, len(lines)
    while a < b and not lines[a].strip():
        a += 1
    while b > a and not lines[b - 1].strip():
        b -= 1
    return lines[a:b]


def _indent(s: str) -> str:
    return s[:len(s) - len(s.lstrip(" \t"))]


def _edges(lines: list[str]) -> tuple[int, int]:
    """(leading, trailing) blank-line counts."""
    core = _strip_blank_edges(lines)
    if not core:
        return len(lines), 0
    lead = next(i for i, ln in enumerate(lines) if ln.strip())
    return lead, len(lines) - lead - len(core)


def _shift(search: list[str], window: list[str]):
    """A function re-indenting replacement lines when window == search up to one uniform indentation offset."""
    pairs = [(s, w) for s, w in zip(search, window) if s.strip() or w.strip()]
    if not pairs or any(not s.strip() or not w.strip() or s.strip() != w.strip() for s, w in pairs):
        return None
    s0, w0 = _indent(pairs[0][0]), _indent(pairs[0][1])
    if w0.endswith(s0):
        add = w0[:len(w0) - len(s0)]
        if all(_indent(w) == add + _indent(s) for s, w in pairs):
            return lambda ln: add + ln if ln.strip() else ln
    if s0.endswith(w0):
        cut = s0[:len(s0) - len(w0)]
        if all(_indent(s) == cut + _indent(w) for s, w in pairs):
            return lambda ln: ln[len(cut):] if ln.startswith(cut) else ln.lstrip(" \t") if ln.strip() else ln
    return None


def find(lines: list[str], search: list[str]) -> tuple[str, list[tuple[int, int, object]]]:
    """(tier, [(start, end, reindent)]) for the first tier with any match; end is exclusive."""
    ident = lambda ln: ln  # noqa: E731
    n = len(search)
    exact = [(i, i + n, ident) for i in range(len(lines) - n + 1) if lines[i:i + n] == search]
    if exact:
        return "exact", exact
    core = _strip_blank_edges(search)
    m = len(core)
    if not m:
        return "none", []
    rs = [ln.rstrip() for ln in core]
    loose = [(i, i + m, ident) for i in range(len(lines) - m + 1)
             if [ln.rstrip() for ln in lines[i:i + m]] == rs]
    if loose:
        return "whitespace", loose
    first = core[0].strip()
    shifted = []
    for i in range(len(lines) - m + 1):
        if lines[i].strip() == first:
            f = _shift(core, lines[i:i + m])
            if f:
                shifted.append((i, i + m, f))
    return ("indentation", shifted) if shifted else ("none", [])


def closest(lines: list[str], search: list[str]) -> tuple[float, int, int]:
    """Best (ratio, start, end) window of len(search) lines: windows are prefiltered by the fuzzy similarity of up to
    three probe lines (a typo leaves no exact line in common), then the best few are compared as a whole."""
    core = _strip_blank_edges(search) or search
    n = max(1, len(core))
    if not lines:
        return 0.0, 0, 0
    sm = difflib.SequenceMatcher(autojunk=False)

    def sim(a: str, b: str) -> float:
        sm.set_seqs(a, b)
        return sm.ratio()

    probes = [(k, ln.strip()) for k, ln in enumerate(core) if ln.strip()][:3] or [(0, "")]
    stripped = [ln.strip() for ln in lines]
    scored = sorted(((sum(sim(p, stripped[i + k]) for k, p in probes if i + k < len(lines)), -i)
                     for i in range(max(1, len(lines) - n + 1))), reverse=True)[:8]
    target = "\n".join(ln.strip() for ln in core)
    best = (0.0, 0, min(n, len(lines)))
    for _, neg in scored:
        i = -neg
        r = difflib.SequenceMatcher(None, target, "\n".join(ln.strip() for ln in lines[i:i + n]), autojunk=False).ratio()
        best = max(best, (r, i, min(i + n, len(lines))))
    return best


def show(lines: list[str], lo: int, hi: int) -> str:
    """Numbered lines lo..hi (1-based, clipped), shortened in the middle when long."""
    lo, hi = max(1, lo), min(len(lines), hi)
    nums = list(range(lo, hi + 1))
    if len(nums) > MAX_SHOWN:
        nums = nums[:MAX_SHOWN // 2] + [0] + nums[-MAX_SHOWN // 2:]
    return "\n".join("     ..." if k == 0 else f"{k:6d}  {lines[k - 1]}" for k in nums) or "      (empty)"


def _unnumber(lines: list[str]) -> list[str] | None:
    """The lines without the 'NNNNNN  ' prefixes this editor prints, when every non-blank line carries one."""
    ms = [NUMBERED_RX.match(ln) for ln in lines if ln.strip()]
    return [NUMBERED_RX.match(ln).group(1) if ln.strip() else ln for ln in lines] if ms and all(ms) else None


def _locate(out: list[str], body: list[str], divs: list[int]):
    """(search, replace, tier, hits) for one block. Each divider is a candidate split; among the splits whose SEARCH
    matches exactly once the longest SEARCH wins (a = line inside old code yields a shorter, wrong SEARCH; one inside
    new code yields a SEARCH that cannot match). Without a unique match the first split is reported."""
    first = best = None
    for d in divs:
        search, repl = body[:d], body[d + 1:]
        if not _strip_blank_edges(search):
            cand = (search, repl, "empty", [])
        else:
            tier, hits = find(out, search)
            plain = _unnumber(search)
            if not hits and plain:
                tier, hits = find(out, plain)
                search, repl, tier = plain, _unnumber(repl) or repl, tier + " and line numbers"
            cand = (search, repl, tier, hits)
        first = first or cand
        if len(cand[3]) == 1 and (best is None or len(cand[0]) > len(best[0])):
            best = cand
    return best or first


def block_key(rel: str, search: list[str], repl: list[str]) -> str:
    return hashlib.sha1(json.dumps([rel, search, repl]).encode()).hexdigest()


def load_journal(root: str) -> set[str]:
    try:
        with open(os.path.join(root, JOURNAL), encoding="ascii") as fh:
            return {ln.strip() for ln in fh if ln.strip()}
    except OSError:
        return set()


def save_journal(root: str, keys: list[str]) -> None:
    try:
        with open(os.path.join(root, JOURNAL), "a", encoding="ascii") as fh:
            fh.write("".join(k + "\n" for k in keys))
    except OSError:
        pass  # only the already-applied report depends on it


def apply_blocks(lines: list[str], blocks, rel: str, journal: set[str] = frozenset()):
    """Apply all blocks in order to a copy; (new lines, report, changed 1-based regions, keys of applied blocks).
    A block whose SEARCH is gone counts as already applied only if this editor applied that exact block before and
    its replacement is still there: the replacement text alone may also occur elsewhere. Raises EditError."""
    out, report, regions, keys = list(lines), [], [], []
    for b, (body, divs) in enumerate(blocks, 1):
        search, repl, tier, hits = _locate(out, body, divs)
        key = block_key(rel, search, repl)
        if tier == "empty":
            raise EditError(f"block {b}: SEARCH is empty. Put the existing lines to replace (or the line just before "
                            "an insertion, repeated in the replacement) between <<<<<<< SEARCH and =======.")
        if len(hits) > 1:
            where = ", ".join(str(h[0] + 1) for h in hits[:8])
            raise EditError(f"block {b}: SEARCH occurs {len(hits)} times in {rel} (starting at lines {where}). Add "
                            "neighbouring lines to SEARCH so it is unique, or replace by line numbers.")
        if not hits:
            done = find(out, repl)[1] if key in journal and _strip_blank_edges(repl) else []
            if done:
                report.append(f"block {b}: already applied (the replacement is at lines {done[0][0] + 1}-{done[0][1]})")
                continue
            r, lo, hi = closest(out, search)
            raise EditError(f"block {b}: SEARCH not found in {rel}. Closest region (similarity {r:.2f}), lines "
                            f"{lo + 1}-{hi}:\n{show(out, lo + 1, hi)}\nCopy SEARCH exactly from these lines, or "
                            f"replace by line numbers: python3 {EDITOR} {rel} {lo + 1}-{hi} <<'EOF' ...new lines... EOF")
        start, end, reindent = hits[0]
        if not tier.startswith("exact"):  # the match ignored blank edges of SEARCH: drop as many from the replacement
            (lead, trail), (rl, rt) = _edges(search), _edges(repl)
            repl = repl[min(lead, rl):len(repl) - min(trail, rt)] if _strip_blank_edges(repl) else []
        new = [reindent(ln) for ln in repl]
        out[start:end] = new
        delta = len(new) - (end - start)
        regions = [(lo + delta, hi + delta) if lo > start else (lo, hi) for lo, hi in regions]
        regions.append((start + 1, start + max(1, len(new))))
        report.append(f"block {b}: replaced lines {start + 1}-{end} ({end - start}) by {len(new)} lines"
                      + ("" if tier == "exact" else f" [matched ignoring {tier}]"))
        keys.append(key)
    return out, report, regions, keys


# ---------- file io ----------
def read_text(full: str) -> tuple[list[str], str, bool]:
    """(lines, eol, final newline). Only a file whose every newline is CRLF is normalised; in a mixed file the CR
    stays part of its lines, so untouched lines are written back byte for byte."""
    with open(full, "rb") as fh:
        data = fh.read().decode("utf-8", "surrogateescape")
    crlf = data.count("\r\n")
    eol = "\r\n" if crlf and crlf == data.count("\n") else "\n"
    if eol == "\r\n":
        data = data.replace("\r\n", "\n")
    final_nl = data.endswith("\n") or not data
    return (data[:-1] if data.endswith("\n") else data).split("\n") if data else [], eol, final_nl


def write_atomic(full: str, lines: list[str], eol: str, final_nl: bool) -> None:
    data = eol.join(lines) + (eol if final_nl and lines else "")
    d = os.path.dirname(full)
    os.makedirs(d, exist_ok=True)
    mode = os.stat(full).st_mode & 0o7777 if os.path.exists(full) else None
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".swe_edit_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode("utf-8", "surrogateescape"))
        if mode is not None:
            os.chmod(tmp, mode)
        else:
            um = os.umask(0)
            os.umask(um)
            os.chmod(tmp, 0o666 & ~um)
        os.replace(tmp, full)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def compile_error(lines: list[str], rel: str) -> str | None:
    if not rel.endswith(".py"):
        return None
    try:
        compile("\n".join(lines) + "\n", rel, "exec", dont_inherit=True)
    except SyntaxError as e:
        ln = e.lineno or 1
        return f"{e.msg} at line {ln}:\n{show(lines, ln - 3, ln + 3)}"
    except Exception:  # null bytes, undecodable text: cannot judge, do not block
        return None
    return None


# ---------- main ----------
def run(argv: list[str], payload: str, root: str) -> int:
    args = [a for a in argv if a != "--"]
    if not args:
        raise EditError(f"no file given. Usage:\n{TEMPLATE}")
    full, rel = resolve(root, args[0])
    rng = RANGE_RX.match(args[1].strip()) if len(args) > 1 else None
    if len(args) > 1 and not rng:
        raise EditError(f"second argument {args[1]!r} is not a line range like 120-125.")
    if not payload.strip() and not rng:
        raise EditError(f"no edit text on stdin. Pass it with a quoted heredoc:\n{TEMPLATE}")
    exists = os.path.isfile(full)
    if not exists:
        if rng:
            raise EditError(f"{rel} does not exist; to create it, call the editor without a line range.")
        blocks = parse_blocks(payload) if any(SEARCH_RX.match(x) for x in payload.split("\n")) else []
        if len(blocks) > 1 or blocks and _strip_blank_edges(blocks[0][0][:blocks[0][1][0]]):
            raise EditError(f"{rel} does not exist (check the path with: ls {os.path.dirname(rel) or '.'}). For a new file "
                            "pass its whole content, with no markers.")
        content = clean_tail(blocks[0][0][blocks[0][1][0] + 1:] if blocks else payload.split("\n"))
        err = compile_error(content, rel)
        if err:
            raise EditError(f"NOT WRITTEN: new file {rel} would not compile ({err})")
        write_atomic(full, content, "\n", True)
        print(f"CREATED {rel} ({len(content)} lines). If it defines public names, export them where the package does "
              "(for example in __init__.py).")
        return 0
    lines, eol, final_nl = read_text(full)
    before_ok = compile_error(lines, rel) is None
    if rng:
        a = int(rng.group(1))
        b = int(rng.group(2)) if rng.group(2) else a
        if not (1 <= a <= len(lines) + 1 and a - 1 <= b <= len(lines)):
            raise EditError(f"lines {a}-{b} are outside {rel} (1-{len(lines)}); {a}-{a - 1} inserts before line {a}.")
        new = clean_tail(payload.split("\n")) if payload.strip() else []
        out = lines[:a - 1] + new + lines[b:]
        report, regions, keys = [f"replaced lines {a}-{b} ({b - a + 1}) by {len(new)} lines"], [(a, a + len(new) - 1)], []
        removed = f"REMOVED (old lines {a}-{b}):\n" + (show(lines, a, b) if b >= a else "      (nothing, insertion)") + "\n"
    else:
        blocks = parse_blocks(payload)
        if not blocks:
            raise EditError(f"no SEARCH/REPLACE block found in the edit text. Format:\n{TEMPLATE}\nor replace by line "
                            f"numbers: python3 {EDITOR} {rel} 120-125 <<'EOF' ...new lines... EOF")
        out, report, regions, keys = apply_blocks(lines, blocks, rel, load_journal(root))
        removed = ""
    if out == lines:
        print(f"NO CHANGE to {rel}: " + "; ".join(report))
        return 0
    err = compile_error(out, rel)
    if err and before_ok:
        raise EditError(f"NOT APPLIED: {rel} would not compile after this edit; {err}\nFix the indentation or the text "
                        "and run the editor again.")
    write_atomic(full, out, eol, final_nl)
    save_journal(root, keys)
    shown = "\n".join(f"NOW lines {max(1, lo - CONTEXT)}-{min(len(out), hi + CONTEXT)}:\n"
                      f"{show(out, lo - CONTEXT, hi + CONTEXT)}" for lo, hi in regions)
    msg = (f"APPLIED to {rel}: " + "; ".join(report) + "\n" + removed + shown
           + ("\nWARNING: the file did not compile before this edit either." if err else ""))
    print(msg if len(msg) <= MAX_OUT else msg[:MAX_OUT - 40] + "\n...[output shortened]")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # file text may hold undecodable bytes: a report must never fail
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    if "--root" in argv:
        k = argv.index("--root")
        root, argv = os.path.realpath(argv[k + 1]), argv[:k] + argv[k + 2:]
    try:
        return run(argv, read_payload(), root or find_root())
    except EditError as e:
        print(f"EDIT NOT APPLIED: {e}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # never leave the agent without guidance
        print(f"EDIT NOT APPLIED: editor failed ({type(e).__name__}: {e}). Replace by line numbers instead: "
              f"python3 {EDITOR} path/to/file.py 120-125 <<'EOF' ...new lines... EOF")
        sys.exit(1)
