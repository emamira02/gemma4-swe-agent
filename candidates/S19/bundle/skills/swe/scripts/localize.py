#!/usr/bin/env python3
"""Rank the repository symbols most likely to need editing for an issue. Offline, stdlib only, read-only.

Signals (validated on the 114 dev tasks, see paper/PAPER.md):
  ident    identifiers / dotted names / file paths from the query resolved against symbol names
           (exact -> dotted suffix -> case-insensitive -> substring, like the harness tools)
  bm25     Okapi BM25 over symbol name tokens (x2) + source tokens
  literal  exact quoted strings / error messages from the query found in source lines
Fusion is mode-dependent: with resolved identifiers (anchored) all lists are fused by reciprocal rank;
without them only the lexical lists are used, because fusing weak anchors dilutes BM25.

Usage: run_skill_script(skill_name="swe", file_path="scripts/localize.py",
                        args={"query": "<identifiers, paths, error text, key words from the issue>"})
Optional: --k N (default 30), --root DIR (default: auto-detect the git workspace).
"""
from __future__ import annotations

import argparse
import ast
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict

T0 = time.monotonic()
TIME_BUDGET_S = 30.0         # stop indexing new files after this; ranking still runs on what was indexed
MAX_FILES = 6000
MAX_FILE_BYTES = 800_000
MAX_OUT_CHARS = 6500          # ranked list, files, literals, tests
SOURCE_MAX_LINES, SOURCE_MAX_CHARS = 80, 4500  # rank-1 source shown in anchored mode
SKIP_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", ".env", "build", "dist",
                       "site-packages", "__pycache__", ".tox", ".nox", ".eggs", ".mypy_cache", ".pytest_cache",
                       ".ruff_cache", "htmlcov", ".idea", ".vscode"})
TEST_RX = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
AUX_RX = re.compile(r"(^|/)(docs?|docs_src|examples?|benchmarks?|scripts|tools|tutorials?)/")
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


# ---- shared with locstudy.signals (kept identical; tests/test_agent.py checks parity) ----
STOP = frozenset("""a an the and or of to in on for with is are be was were it this that as by at from not no can
could should would will may might do does did has have had i we you they he she my our your if then else when
but so use using used get set add new return true false none self cls def class import from print len list dict
str int float bool type object value values key keys item items error errors issue bug fix feature support
example code test tests python version file files function method""".split())
_SPLIT = re.compile(r"[A-Za-z][a-z0-9]*|[0-9]+")


def toks(s: str) -> list[str]:
    return [t.lower() for t in _SPLIT.findall(s.replace("_", " ")) if t.lower() not in STOP and len(t) > 1]


_IDENT = [re.compile(p) for p in (r"`([^`\n]{2,80})`", r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b",
                                  r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b", r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b",
                                  r"\b([A-Za-z_]\w{2,})\(")]
_TRACE = re.compile(r'File "([^"]+?\.py)", line \d+, in (\w+)')


def extract_identifiers(text: str) -> list[str]:
    seen: Counter = Counter()
    for rx in _IDENT:
        for m in rx.finditer(text):
            tok = m.group(1).strip().strip("()").split("(")[0]
            for t in re.split(r"[\s,]+", tok):
                t = t.strip(".:;'\"")
                if len(t) >= 3 and t.lower() not in STOP and not t.isdigit():
                    seen[t] += 1
    return [t for t, _ in seen.most_common()]


class BM25:
    """Okapi BM25 (k1=1.2, b=0.75) over token lists; pure Python, sparse postings."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.n = len(docs)
        avg = (sum(len(d) for d in docs) / self.n) if self.n else 1.0
        self.norm = [k1 * (1 - b + b * len(d) / (avg or 1.0)) for d in docs]
        self.k1 = k1
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.post[t].append((i, f))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for t in set(query):
            for i, f in self.post.get(t, ()):
                out[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.norm[i])
        return out


def rrf(lists: list[list[str]], k: int = 60, depth: int = 200) -> dict[str, float]:
    s: dict[str, float] = defaultdict(float)
    for lst in lists:
        for r, n in enumerate(lst[:depth]):
            s[n] += 1.0 / (k + r + 1)
    return s


# ---- workspace discovery ----
def find_root(cli_root: str | None) -> str:
    if cli_root:  # explicit choice always wins
        return os.path.realpath(cli_root)
    cands = [os.environ.get("SWE_WORKSPACE"), os.environ.get("PWD"),
             *os.environ.get("PYTHONPATH", "").split(os.pathsep), "/workspace"]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return os.path.realpath(c)
    for c in cands:
        if c and os.path.isdir(c) and os.path.realpath(c) != os.path.realpath(os.getcwd()):
            return os.path.realpath(c)
    return "/workspace"


def list_py_files(root: str) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                              "--", "*.py"], capture_output=True, timeout=20, check=True).stdout
        files = sorted({f for f in out.decode("utf-8", "replace").split("\0") if f.endswith(".py")})
        files = [f for f in files if not (set(f.split("/")[:-1]) & SKIP_DIRS)]
        if files:
            return files[:MAX_FILES]
    except Exception:
        pass
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(fns):
            if fn.endswith(".py"):
                files.append(os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, "/"))
                if len(files) >= MAX_FILES:
                    return files
    return files


def module_name(path: str) -> str:
    parts = path[:-3].split("/")
    if parts and parts[0] in ("src", "lib") and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


# ---- symbol table ----
class Sym:
    __slots__ = ("qual", "short", "path", "start", "end", "sig", "doc", "text", "aux")

    def __init__(self, qual, short, path, start, end, sig, doc, text, aux):
        self.qual, self.short, self.path, self.start, self.end = qual, short, path, start, end
        self.sig, self.doc, self.text, self.aux = sig, doc, text, aux


def _signature(lines: list[str], node) -> str:
    """The def/class header, joined across continuation lines (at most 4)."""
    i, out, depth = node.lineno - 1, [], 0
    while i < len(lines) and len(out) < 4:
        s = lines[i].strip()
        out.append(s)
        depth += s.count("(") + s.count("[") - s.count(")") - s.count("]")
        if s.endswith(":") and depth <= 0:
            break
        i += 1
    sig = " ".join(out)
    return sig if len(sig) <= 140 else sig[:137] + "..."


def symbols_of(path: str, src: str) -> list[Sym]:
    aux = bool(AUX_RX.search(path))
    mod = module_name(path)
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return [Sym(mod, os.path.basename(path), path, 1, max(1, len(lines)), "(unparsable module)", "", src, aux)]
    out: list[Sym] = []
    covered: set[int] = set()

    def visit(body, prefix: list[str]):
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            end = getattr(node, "end_lineno", None) or node.lineno
            covered.update(range(start, end + 1))
            names = prefix + [node.name]
            try:
                doc = (ast.get_docstring(node) or "").strip().splitlines()
            except Exception:
                doc = []
            doc1 = doc[0][:80] if doc else ""
            if isinstance(node, ast.ClassDef):
                members = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                head_end = (min(n.lineno for n in members) - 1) if members else end
                text = "\n".join(lines[start - 1:max(start, head_end)]) + "\n" + " ".join(n.name for n in members)
            else:
                text = "\n".join(lines[start - 1:end])
            out.append(Sym(mod + "." + ".".join(names), ".".join(names), path, start, end,
                           _signature(lines, node), doc1, text, aux))
            if isinstance(node, ast.ClassDef):
                visit(node.body, names)

    visit(tree.body, [])
    rest = [ln for i, ln in enumerate(lines, 1) if i not in covered and ln.strip()]
    if rest:
        out.append(Sym(mod + ".<module>", "<module>", path, 1, len(lines), "module-level code (imports, constants)",
                       "", "\n".join(rest), aux))
    return out


# ---- query analysis ----
_QUOTED = re.compile(r"\"([^\"\n]{6,160})\"|'([^'\n]{6,160})'|`([^`\n]{6,160})`")
_ERRLINE = re.compile(r"\b[A-Z]\w*(?:Error|Exception|Warning):[ \t]*([^\n]{6,160})")
_PATHLIKE = re.compile(r"\b([\w./-]+\.py)\b")


def literals(query: str) -> list[str]:
    out = []
    for m in _QUOTED.finditer(query):
        s = next(g for g in m.groups() if g)
        if len(toks(s)) >= 1 and not re.fullmatch(r"[\w.]+", s):  # identifiers are handled by `ident`
            out.append(s.strip())
    for m in _ERRLINE.finditer(query):
        out.append(m.group(1).strip().strip("'\"."))
    seen, res = set(), []
    for s in out:
        if len(s) >= 6 and s not in seen:
            seen.add(s)
            res.append(s)
    return res[:8]


class Index:
    def __init__(self, syms: list[Sym]):
        self.syms = syms
        self.by_qual = {s.qual: s for s in syms}
        self.by_tail: dict[str, list[str]] = defaultdict(list)
        self.by_tail_lower: dict[str, list[str]] = defaultdict(list)
        self.by_path: dict[str, list[Sym]] = defaultdict(list)
        for s in syms:
            self.by_path[s.path].append(s)
            if s.short == "<module>":
                continue
            tail = s.qual.rsplit(".", 1)[-1]
            self.by_tail[tail].append(s.qual)
            self.by_tail_lower[tail.lower()].append(s.qual)

    def resolve(self, tok: str) -> list[tuple[int, str]]:
        if tok in self.by_qual:
            return [(0, tok)]
        tail = tok.rsplit(".", 1)[-1]
        out = [(1, q) for q in self.by_tail.get(tail, ()) if q.endswith("." + tok) or q.rsplit(".", 1)[-1] == tok]
        if out:
            return out
        out = [(2, q) for q in self.by_tail_lower.get(tail.lower(), ())]
        if out or len(tail) < 5:
            return out
        low = tail.lower()
        return [(3, q) for q in self.by_qual if low in q.rsplit(".", 1)[-1].lower()][:50]


def rank_ident(idx: Index, query: str) -> tuple[list[str], list[str]]:
    weights = (1.0, 0.8, 0.5, 0.2)
    score: dict[str, float] = defaultdict(float)
    anchors = []
    toks_ = [fn for _, fn in _TRACE.findall(query)] + extract_identifiers(query)
    for pos, tok in enumerate(toks_[:40]):
        hits = idx.resolve(tok)
        if not hits:
            continue
        anchors.append(tok)
        w = 1.0 / (1 + math.log1p(len(hits))) / (1 + 0.05 * pos)
        for tier, q in hits:
            score[q] += w * weights[tier]
    # file paths named in the query anchor every symbol of that file (weakly)
    for p in sorted({m.group(1).lstrip("./") for m in _PATHLIKE.finditer(query)}):
        for path, syms in idx.by_path.items():
            if path == p or path.endswith("/" + p):
                for s in syms:
                    score[s.qual] += 0.3
                if p not in anchors:
                    anchors.append(p)
    ranked = [q for q, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))]
    return ranked, anchors[:8]


def rank_literal(idx: Index, lits: list[str], texts: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    hits: dict[str, float] = defaultdict(float)
    found = []
    for lit in lits:
        variants = {lit, lit.rstrip(".!"), lit[:60]}
        for path, lines in texts.items():
            for i, ln in enumerate(lines, 1):
                if any(v and v in ln for v in variants):
                    best = None
                    for s in idx.by_path.get(path, ()):  # most specific symbol containing the line
                        if s.start <= i <= s.end and (best is None or s.end - s.start < best.end - best.start):
                            best = s
                    if best is not None:
                        hits[best.qual] += 1.0
                        found.append(f'"{lit[:50]}" -> {path}:{i}')
    return [q for q, _ in sorted(hits.items(), key=lambda x: (-x[1], x[0]))], found[:6]


def related_tests(top: list[Sym], test_texts: dict[str, str]) -> list[str]:
    names = []
    for s in top[:6]:
        tail = s.short.rsplit(".", 1)[-1]
        if tail != "<module>" and len(tail) >= 4 and tail not in names:
            names.append(tail)
    scored = []
    for path, text in test_texts.items():
        c = sum(len(re.findall(r"\b" + re.escape(n) + r"\b", text)) for n in names)
        if c:
            scored.append((-c, path))
    return [f"{p} ({-c} refs)" for c, p in sorted(scored)[:5]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--query", default="")
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--root", default=None)
    a, rest = ap.parse_known_args(argv)
    query = " ".join([a.query, *[r for r in rest if r != "--"]]).strip()
    root = find_root(a.root)
    try:  # every exit path installs the editor: the S9 panel lost 4 edits after a "No symbol matches" early return
        return localize(query, max(5, min(a.k, 60)), root)
    finally:
        print(install_editor(root))


def localize(query: str, k: int, root: str) -> int:
    if not query:
        print("ERROR: pass args={\"query\": \"<identifiers, file paths, error text, key words from the issue>\"}")
        return 2
    files = list_py_files(root)
    syms: list[Sym] = []
    src_texts: dict[str, list[str]] = {}
    test_texts: dict[str, str] = {}
    truncated = False
    for f in files:
        if time.monotonic() - T0 > TIME_BUDGET_S:
            truncated = True
            break
        full = os.path.join(root, f)
        try:
            if os.path.getsize(full) > MAX_FILE_BYTES:
                continue
            with open(full, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        if TEST_RX.search(f):
            test_texts[f] = src
            continue
        src_texts[f] = src.splitlines()
        syms.extend(symbols_of(f, src))
    if not syms:
        print(f"No Python source found under {root}. Search with run_command instead: grep -rn -i \"term\" . | head -40")
        return 1
    idx = Index(syms)
    bm = BM25([toks(s.qual) * 2 + toks(s.text) for s in syms])
    qtok = toks(query)
    sc = bm.scores(qtok)
    bm25 = [syms[i].qual for i, _ in sorted(sc.items(), key=lambda x: (-x[1], syms[x[0]].qual))][:300]
    ident, anchors = rank_ident(idx, query)
    lits = literals(query)
    literal, lit_found = rank_literal(idx, lits, src_texts) if lits else ([], [])
    mode = "anchored" if ident else "lexical"
    fused = rrf([ident, bm25, literal] if ident else [bm25, literal] if literal else [bm25])
    for q in fused:  # docs/examples/benchmarks rank after library code at equal evidence
        if idx.by_qual[q].aux:
            fused[q] *= 0.5
    order = [q for q, _ in sorted(fused.items(), key=lambda x: (-x[1], x[0]))]
    top = [idx.by_qual[q] for q in order[:k]]
    if not top:
        print(f"No symbol matches the query (indexed {len(files)} files, {len(syms)} symbols). Add identifiers, "
              "file names or distinctive words from the issue, or search: grep -rn -i '<term>' --include='*.py' . | head -40")
        return 0

    out = [f"mode: {mode}" + (f" (resolved: {', '.join(anchors)})" if anchors else
                             " (no symbol named in the query resolved; ranking is lexical)")
           + f" | indexed {len(files)} files, {len(syms)} symbols" + (" [time budget hit: partial index]" if truncated else ""),
           "TOP SYMBOLS (path:first-last line, symbol, signature  # doc). Re-rank them with the issue in mind, "
           "then read_file the best 1-3 ranges:"]
    for r, s in enumerate(top, 1):
        line = f"{r:2d}. {s.path}:{s.start}-{s.end}  {s.short}  {s.sig}" + (f"  # {s.doc}" if s.doc else "")
        out.append(line if len(line) <= 220 else line[:217] + "...")
    files_rank = Counter()
    for r, s in enumerate(top):
        files_rank[s.path] += 1.0 / (r + 1)
    out.append("FILES: " + ", ".join(p for p, _ in files_rank.most_common(6)))
    if lit_found:
        out.append("LITERAL MATCHES: " + "; ".join(lit_found))
    rt = related_tests(top, test_texts)
    if rt:
        out.append("RELATED TESTS (check one with: cd /workspace && timeout 100 python -m pytest -x -q FILE -k NAME 2>&1 | tail -25): "
                   + ", ".join(rt))
    text = "\n".join(out)
    if len(text) > MAX_OUT_CHARS:
        text = text[:MAX_OUT_CHARS - 20] + "\n...[truncated]"
    print(text + source_block(top, mode, src_texts))
    return 0


def source_block(top: list[Sym], mode: str, src_texts: dict[str, list[str]]) -> str:
    """When the issue names a symbol (anchored mode, where rank 1 is most precise), show rank 1's source so the
    model can edit without a read_file round trip. Raw lines, no numbers: the editor's SEARCH text is copied from it."""
    if mode != "anchored" or not top:
        return ""
    s = top[0]
    n = s.end - s.start + 1
    if s.short == "<module>" or n > SOURCE_MAX_LINES:
        return ""
    body = "\n".join(src_texts.get(s.path, [])[s.start - 1:s.end])
    if not body.strip() or len(body) > SOURCE_MAX_CHARS:
        return ""
    return (f"\nSOURCE OF #1 {s.path} lines {s.start}-{s.end} (exact text; if this is the place to fix, copy the SEARCH "
            f"lines from it and edit without reading the file again):\n----- begin -----\n{body}\n----- end -----")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # never leave the agent without guidance
        print(f"localize failed ({type(e).__name__}: {e}). Fall back to: grep -rn '<term>' --include=*.py . | head -30")
        sys.exit(0)
