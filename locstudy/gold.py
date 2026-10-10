"""Gold labels: which graph symbols does the reference patch edit? Includes a label-quality cross-check."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@ ?(.*)$")
_HEADER_NAME = re.compile(r"\b(?:async\s+def|def|class)\s+([A-Za-z_]\w*)")
_NON_SOURCE = re.compile(r"(^|/)(tests?|testing|docs|docs_src|examples?)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
MIN_LINE = 4  # stripped lines shorter than this ('}', 'pass', ')') carry no location signal


@dataclass
class Hunk:
    header: str = ""
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)


@dataclass
class Gold:
    symbols: set[str]
    files: set[str]
    hunks_total: int
    hunks_mapped: int
    header_checked: int   # hunks whose @@ header names an enclosing def/class
    header_agree: int     # ... and that name is a component of the chosen gold symbol
    edit_hunks: int = 0   # mapped hunks with removed signal lines
    edit_full_cov: int = 0  # ... whose removed signal lines all lie inside the chosen symbol


def parse_patch(patch: str) -> dict[str, list[Hunk]]:
    files: dict[str, list[Hunk]] = {}
    cur, hunk = None, None
    for line in patch.splitlines():
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[4:].split("\t")[0].strip()
            cur = None if path == "/dev/null" else (path[2:] if path.startswith("b/") else path)
            if cur is not None:
                files.setdefault(cur, [])
            hunk = None
        elif line.startswith("diff --git"):
            cur, hunk = None, None
        elif line.startswith("@@") and cur is not None:
            m = _HEADER.match(line)
            hunk = Hunk(header=(m.group(1) if m else "").strip())
            files[cur].append(hunk)
        elif hunk is not None:
            if line.startswith("-"):
                hunk.removed.append(line[1:])
            elif line.startswith("+"):
                hunk.added.append(line[1:])
            elif line.startswith(" "):
                hunk.context.append(line[1:])
    return files


def is_source(path: str) -> bool:
    p = path.lower()
    return p.endswith(".py") and not _NON_SOURCE.search(p)


def module_candidates(path: str) -> list[str]:
    """Dotted names a file may appear under in node ids (leading dirs such as src/ or docs_src/ may be dropped).
    Single-component names are kept only for top-level files to avoid spurious prefix matches."""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    cands = [".".join(parts[i:]) for i in range(len(parts)) if len(parts[i:]) >= 2 or len(parts) == 1]
    return cands or [".".join(parts)]


def node_file(nid: str, file_modules: dict[str, str]) -> str | None:
    """The gold file a node belongs to (longest module prefix). Package __init__ files own direct children only."""
    best = None
    for mod, f in file_modules.items():
        if not (nid == mod or nid.startswith(mod + ".")):
            continue
        if f.endswith("__init__.py") and nid.count(".") != mod.count(".") + 1:
            continue
        if best is None or len(mod) > len(best[0]):
            best = (mod, f)
    return best[1] if best else None


_MODULE_LEVEL = ("import ", "from ", "#")


def _signal_lines(lines: list[str]) -> list[str]:
    """Stripped lines that can locate an edit: long enough, and not imports/comments (module-level by nature)."""
    return [s for s in (l.strip() for l in lines) if len(s) >= MIN_LINE and not s.startswith(_MODULE_LEVEL)]


def gold_for(patch: str, nodes: dict[str, str], min_cov: float = 0.5) -> Gold:
    """Per hunk: the most specific node whose source contains >= min_cov of the hunk's removed signal lines
    (pure additions: >= 2 context lines). Most specific = most matched removed lines, then context lines, then the
    shortest source. min_cov=0.5 is the pre-registered strict setting; min_cov~0 reproduces the lenient labels."""
    symbols, files = set(), set()
    total = mapped = checked = agree = edit = full = 0
    line_sets = {}
    for path, hunks in parse_patch(patch).items():
        if not is_source(path):
            continue
        files.add(path)
        mods = module_candidates(path)
        cands = [nid for nid in nodes if any(nid.startswith(m + ".") for m in mods)]
        for h in hunks:
            total += 1
            removed = _signal_lines(h.removed)
            ctx = _signal_lines(h.context)
            best = None
            for nid in cands:
                lines = line_sets.get(nid)
                if lines is None:
                    lines = line_sets[nid] = {l.strip() for l in nodes[nid].splitlines()}
                r = sum(l in lines for l in removed)
                c = sum(l in lines for l in ctx)
                if (removed and r >= 1 and r / len(removed) >= min_cov) or (not removed and c >= 2):
                    key = (r, c, -len(nodes[nid]), nid)
                    if best is None or key > best:
                        best = key
            if best is None:
                continue
            mapped += 1
            symbols.add(best[3])
            if removed:
                edit += 1
                full += best[0] == len(removed)
            m = _HEADER_NAME.search(h.header)
            if m:
                checked += 1
                agree += m.group(1) in best[3].split(".")
    return Gold(symbols, files, total, mapped, checked, agree, edit, full)
