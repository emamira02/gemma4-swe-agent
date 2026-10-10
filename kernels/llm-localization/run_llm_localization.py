from __future__ import annotations

# ======== locstudy/__init__.py ========
"""locstudy: measurement of issue-localization signals for the Gemma 4 Developer Agent benchmark.

Modules: data (tasks, graphs, manifest) -> gold (labels from reference patches) -> signals (rankers)
-> metrics (hit ranks, budgets, bootstrap CIs, paired tests) -> study (end-to-end run) -> report (tables, figures).
"""
SCHEMA_VERSION = 2

# ======== locstudy/signals.py ========
"""Ranking signals computed from the issue text only (no patch, no tests)."""

import math
import re
from collections import Counter, defaultdict

import numpy as np

STOP = frozenset("""a an the and or of to in on for with is are be was were it this that as by at from not no can
could should would will may might do does did has have had i we you they he she my our your if then else when
but so use using used get set add new return true false none self cls def class import from print len list dict
str int float bool type object value values key keys item items error errors issue bug fix feature support
example code test tests python version file files function method""".split())
_SPLIT = re.compile(r"[A-Za-z][a-z0-9]*|[0-9]+")


def toks(s: str) -> list[str]:
    return [t.lower() for t in _SPLIT.findall(s.replace("_", " ")) if t.lower() not in STOP and len(t) > 1]


class BM25:
    """Okapi BM25 with a sparse inverted index (vectorised scoring)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.n = len(docs)
        self.k1, self.b = k1, b
        lens = np.array([len(d) for d in docs], dtype=np.float64)
        self.norm = k1 * (1 - b + b * lens / (lens.mean() if self.n else 1.0))
        self.post: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        acc: dict[str, dict[int, int]] = defaultdict(dict)
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                acc[t][i] = f
        self.idf = {}
        for t, p in acc.items():
            idx = np.fromiter(p.keys(), dtype=np.int64)
            tf = np.fromiter(p.values(), dtype=np.float64)
            self.post[t] = (idx, tf)
            self.idf[t] = math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5))

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.n)
        for t in set(query):
            if t in self.post:
                idx, tf = self.post[t]
                out[idx] += self.idf[t] * tf * (self.k1 + 1) / (tf + self.norm[idx])
        return out

    def rank(self, query: list[str], ids: list[str], limit: int = 500) -> list[str]:
        sc = self.scores(query)
        order = np.argsort(-sc, kind="stable")[:limit]
        return [ids[i] for i in order if sc[i] > 0]


# ---------- identifier extraction ----------
_IDENT = [re.compile(p) for p in (r"`([^`\n]{2,80})`", r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b",
                                  r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b", r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b",
                                  r"\b([A-Za-z_]\w{2,})\(")]
_TRACE = re.compile(r'File "([^"]+?\.py)", line \d+, in (\w+)')
_CODEBLOCK = re.compile(r"```.*?```", re.S)
_IMPORT = re.compile(r"\bfrom\s+([\w.]+)\s+import\s+\(?([\w, \n]+)\)?")
_CALL = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*\(")


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


def extract_identifiers_plus(text: str) -> list[str]:
    """extract_identifiers + traceback frames, imports and dotted calls inside fenced code blocks (weighted)."""
    score: Counter = Counter()
    for path, fn in _TRACE.findall(text):
        score[fn] += 3
        mods = module_candidates(path.replace("\\", "/").split("site-packages/")[-1])
        if mods:
            score[f"{mods[0]}.{fn}"] += 3
    for block in _CODEBLOCK.findall(text):
        for mod, names in _IMPORT.findall(block):
            for n in re.split(r"[,\s]+", names):
                if n and n != "as":
                    score[f"{mod}.{n}"] += 2
        for call in _CALL.findall(block):
            score[call] += 1
    for i, tok in enumerate(extract_identifiers(text)):
        score[tok] += 1 + 1.0 / (1 + i)
    return [t for t, _ in score.most_common() if len(t) >= 3 and t.lower() not in STOP]


class SymbolIndex:
    """Harness-like symbol resolution: exact id -> dotted suffix / last component -> case-insensitive -> substring."""
    TIER_WEIGHT = (1.0, 0.8, 0.5, 0.2)

    def __init__(self, ids: list[str]):
        self.ids = ids
        self.all = set(ids)
        self.by_tail: dict[str, list[str]] = defaultdict(list)
        self.by_tail_lower: dict[str, list[str]] = defaultdict(list)
        for nid in ids:
            tail = nid.rsplit(".", 1)[-1]
            self.by_tail[tail].append(nid)
            self.by_tail_lower[tail.lower()].append(nid)

    def resolve(self, tok: str) -> list[tuple[int, str]]:
        if tok in self.all:
            return [(0, tok)]
        tail = tok.rsplit(".", 1)[-1]
        out = [(1, n) for n in self.by_tail.get(tail, ()) if n.endswith("." + tok) or n.rsplit(".", 1)[-1] == tok]
        if out:
            return out
        out = [(2, n) for n in self.by_tail_lower.get(tail.lower(), ())]
        if out or len(tail) < 5:
            return out
        low = tail.lower()
        return [(3, n) for n in self.ids if low in n.rsplit(".", 1)[-1].lower()][:50]

    def rank(self, tokens: list[str], max_tokens: int = 40) -> list[str]:
        scored: dict[str, float] = defaultdict(float)
        for pos, tok in enumerate(tokens[:max_tokens]):
            hits = self.resolve(tok)
            if not hits:
                continue
            w = 1.0 / (1 + math.log1p(len(hits))) / (1 + 0.05 * pos)
            for tier, nid in hits:
                scored[nid] += w * self.TIER_WEIGHT[tier]
        return [n for n, _ in sorted(scored.items(), key=lambda x: (-x[1], x[0]))]


def rrf(lists: list[list[str]], k: int = 60, depth: int = 200) -> list[str]:
    """Reciprocal-rank fusion (Cormack et al., 2009); ties broken by id for determinism."""
    s: dict[str, float] = defaultdict(float)
    for lst in lists:
        for r, n in enumerate(lst[:depth]):
            s[n] += 1.0 / (k + r + 1)
    return [n for n, _ in sorted(s.items(), key=lambda x: (-x[1], x[0]))]


def expand(anchors: list[str], adj: dict, hops: int) -> list[str]:
    """Breadth-first call-graph expansion; anchors first, then hop-1 neighbours, then hop-2 ..."""
    out, seen, frontier = list(anchors), set(anchors), list(anchors)
    for _ in range(hops):
        nxt = []
        for n in frontier:
            for m in sorted(adj.get(n, ())):
                if m not in seen:
                    seen.add(m)
                    out.append(m)
                    nxt.append(m)
        frontier = nxt
    return out


def hop_distance(anchors: list[str], gold: set[str], adj: dict, max_d: int = 4) -> int | None:
    frontier, seen = set(anchors), set(anchors)
    for d in range(max_d + 1):
        if frontier & gold:
            return d
        frontier = {m for n in frontier for m in adj.get(n, ())} - seen
        seen |= frontier
        if not frontier:
            return None
    return None

# ======== locstudy/gold.py ========
"""Gold labels: which graph symbols does the reference patch edit? Includes a label-quality cross-check."""

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

# ======== locstudy/data.py ========
"""Task and repository-graph loading, plus a content manifest for provenance."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np



@dataclass(frozen=True)
class Task:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    hints_text: str
    patch: str

    @property
    def graph_key(self) -> str:
        return f"{self.repo.split('/')[1].lower()}_{self.base_commit}"


def load_tasks(data_dir: Path) -> list[Task]:
    out = []
    for line in (Path(data_dir) / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.append(Task(d["instance_id"], d["repo"], d["base_commit"], d["problem_statement"],
                            d.get("hints_text") or "", d["patch"]))
    ids = [t.instance_id for t in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate instance_id in tasks.jsonl")
    return out


@dataclass
class RepoGraph:
    nodes: dict[str, str]            # node id -> source text
    ids: list[str]
    emb: np.ndarray                  # L2-normalised float32, row i = ids[i]
    adj: dict[str, set[str]]         # undirected call graph
    index: SymbolIndex
    bm25: BM25
    pos: dict[str, int]

    def neighbors_by_embedding(self, anchors: list[str], limit: int = 500) -> list[str]:
        if not anchors:
            return []
        sims = self.emb @ self.emb[[self.pos[a] for a in anchors]].T
        return [self.ids[i] for i in np.argsort(-sims.max(axis=1), kind="stable")[:limit]]


@lru_cache(maxsize=2)
def load_graph(data_dir: str, key: str, k1: float = 1.2, b: float = 0.75) -> RepoGraph:
    data = Path(data_dir)
    g = json.loads((data / "graphs" / f"{key}.json").read_text(encoding="utf-8"))
    nodes = {n["id"]: n.get("text") or "" for n in g["nodes"]}
    ids = list(nodes)
    with np.load(data / "embeddings" / f"{key}.npz", allow_pickle=False) as z:
        missing = [i for i in ids if i not in z.files]
        if missing:
            raise ValueError(f"{key}: {len(missing)} nodes without embedding")
        emb = np.stack([z[i] for i in ids]).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12
    adj: dict[str, set[str]] = defaultdict(set)
    for e in g["edges"]:
        if e["source"] in nodes and e["target"] in nodes and e["source"] != e["target"]:
            adj[e["source"]].add(e["target"])
            adj[e["target"]].add(e["source"])
    bm = BM25([toks(nid.replace(".", " ")) * 2 + toks(nodes[nid]) for nid in ids], k1=k1, b=b)
    return RepoGraph(nodes, ids, emb, adj, SymbolIndex(ids), bm, {n: i for i, n in enumerate(ids)})


def manifest(data_dir: Path) -> dict:
    """Content hashes of everything the study reads (tasks fully; graphs/embeddings by name + size + content)."""
    data = Path(data_dir)

    def h(p: Path) -> str:
        d = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                d.update(chunk)
        return d.hexdigest()
    out = {"tasks.jsonl": h(data / "tasks.jsonl")}
    for sub in ("graphs", "embeddings"):
        agg = hashlib.sha256()
        files = sorted((data / sub).iterdir())
        for p in files:
            agg.update(p.name.encode())
            agg.update(h(p).encode())
        out[sub] = {"files": len(files), "sha256": agg.hexdigest()}
    return out

# ======== locstudy/metrics.py ========
"""Per-task retrieval outcomes and task-level inference (bootstrap CIs, paired bootstrap, exact McNemar)."""

import math

import numpy as np

KS = (1, 5, 10, 20, 50)
BUDGETS_TOKENS = (2_000, 8_000, 32_000)   # 32k = the harness' context window
CHARS_PER_TOKEN = 4                        # coarse, stated approximation for source code


def first_hit(ranked: list[str], gold: set[str]) -> int | None:
    """0-based rank of the first gold item, or None."""
    return next((i for i, n in enumerate(ranked) if n in gold), None)


def tokens_to_hit(ranked: list[str], gold: set[str], nodes: dict[str, str]) -> int | None:
    """Approximate tokens an agent reads (full source of each ranked symbol, in order) until the first gold one."""
    total = 0
    for n in ranked:
        total += max(1, len(nodes.get(n, "")) // CHARS_PER_TOKEN)
        if n in gold:
            return total
    return None


def gold_coverage(ranked: list[str], gold: set[str], k: int) -> float:
    return len(gold & set(ranked[:k])) / len(gold) if gold else 0.0


def outcome(ranked: list[str], gold: set[str], nodes: dict[str, str]) -> dict:
    """Everything later aggregation needs, per task and signal."""
    return {"rank": first_hit(ranked, gold), "tokens": tokens_to_hit(ranked, gold, nodes),
            "cov10": round(gold_coverage(ranked, gold, 10), 4), "list_len": len(ranked)}


def hits_at(outcomes: list[dict], k: int) -> np.ndarray:
    return np.array([o["rank"] is not None and o["rank"] < k for o in outcomes], dtype=float)


def rr(outcomes: list[dict]) -> np.ndarray:
    return np.array([1.0 / (o["rank"] + 1) if o["rank"] is not None else 0.0 for o in outcomes])


def hits_within_budget(outcomes: list[dict], budget: int) -> np.ndarray:
    return np.array([o["tokens"] is not None and o["tokens"] <= budget for o in outcomes], dtype=float)


def bootstrap_ci(values: np.ndarray, n_boot: int = 10_000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean and percentile CI with task-level resampling."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, v.size, size=(n_boot, v.size))].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(v.mean()), float(lo), float(hi)


def paired_bootstrap(a: np.ndarray, b: np.ndarray, n_boot: int = 10_000, seed: int = 0,
                     alpha: float = 0.05) -> dict:
    """Mean difference a-b with percentile CI and a two-sided bootstrap p-value (sign-flip style)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.shape != b.shape or a.size == 0:
        raise ValueError("paired arrays must be non-empty and equal length")
    d = a - b
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, d.size, size=(n_boot, d.size))].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    centered = means - d.mean()
    p = float(min(1.0, (np.sum(np.abs(centered) >= abs(d.mean())) + 1) / (n_boot + 1)))
    return {"diff": float(d.mean()), "lo": float(lo), "hi": float(hi), "p_boot": p}


def mcnemar_exact(a_hits: np.ndarray, b_hits: np.ndarray) -> dict:
    """Exact two-sided McNemar test on paired binary outcomes (binomial on discordant pairs)."""
    a, b = np.asarray(a_hits, bool), np.asarray(b_hits, bool)
    n01 = int(np.sum(~a & b))   # b right, a wrong
    n10 = int(np.sum(a & ~b))   # a right, b wrong
    n = n01 + n10
    if n == 0:
        return {"a_only": n10, "b_only": n01, "p": 1.0}
    k = min(n01, n10)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {"a_only": n10, "b_only": n01, "p": float(min(1.0, 2 * p))}


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values for a family of comparisons."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (name, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[name] = running
    return out

# ======== locstudy/study.py ========
"""End-to-end study: per-task outcomes for every signal, then aggregates with CIs, paired tests, sensitivity."""

import datetime as dt
import json
import platform
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np



@dataclass(frozen=True)
class Params:
    """Fixed before looking at results; sensitivity() varies them one at a time."""
    rrf_k: int = 60
    n_anchors: int = 3
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    gold_min_cov: float = 0.5
    n_boot: int = 10_000
    seed: int = 0


SIGNALS = ("ident", "ident+", "bm25", "emb", "graph", "graph2", "rrf", "rrf+")
PRIMARY = "rrf+"
_FEATURE = re.compile(r"^\W*(✨|➕|🎉|add\b|adds\b|added\b|support\b|introduce|implement|allow|new\b|feature)", re.I)
_BUG = re.compile(r"^\W*(🐛|fix|fixes|fixed|bug|error|crash|regression|incorrect|wrong|broken|fail)", re.I)


def task_type(issue: str) -> str:
    """Heuristic from the first line of the issue/PR title; reported as such, never used for ranking."""
    first = issue.strip().splitlines()[0] if issue.strip() else ""
    if _BUG.search(first):
        return "bug"
    if _FEATURE.search(first):
        return "feature"
    return "other"


def rankings(task: Task, data_dir: str, p: Params) -> tuple[dict[str, list[str]], object, dict]:
    g = load_graph(data_dir, task.graph_key, p.bm25_k1, p.bm25_b)
    issue = task.problem_statement
    r_ident = g.index.rank(extract_identifiers(issue))
    r_identp = g.index.rank(extract_identifiers_plus(issue))
    r_bm25 = g.bm25.rank(toks(issue), g.ids)
    anchors = (r_ident or r_bm25)[: p.n_anchors]
    anchors_p = (r_identp or r_bm25)[: p.n_anchors]
    lists = {"ident": r_ident, "ident+": r_identp, "bm25": r_bm25,
             "emb": g.neighbors_by_embedding(anchors), "graph": expand(anchors, g.adj, 1),
             "graph2": expand(anchors_p, g.adj, 2)}
    lists["rrf"] = rrf([lists["ident"], lists["bm25"], lists["emb"], lists["graph"]], k=p.rrf_k)
    lists["rrf+"] = rrf([lists["ident+"], lists["bm25"], g.neighbors_by_embedding(anchors_p), lists["graph2"]], k=p.rrf_k)
    return lists, g, {"anchors_from_ident": bool(r_identp), "anchors": anchors_p}


def per_task(data_dir: Path, p: Params, log=print) -> list[dict]:
    rows = []
    tasks = load_tasks(data_dir)
    for i, t in enumerate(tasks):
        if i % 20 == 0:
            log(f"[{i}/{len(tasks)}]")
        g = load_graph(str(data_dir), t.graph_key, p.bm25_k1, p.bm25_b)
        gold = gold_for(t.patch, g.nodes, p.gold_min_cov)
        row = {"id": t.instance_id, "repo": t.repo, "type": task_type(t.problem_statement),
               "source_change": bool(gold.files), "n_gold": len(gold.symbols),
               "hunks_total": gold.hunks_total, "hunks_mapped": gold.hunks_mapped,
               "header_checked": gold.header_checked, "header_agree": gold.header_agree,
               "edit_hunks": gold.edit_hunks, "edit_full_cov": gold.edit_full_cov}
        if gold.files:
            lists, g, info = rankings(t, str(data_dir), p)
            fm = {m: f for f in gold.files for m in module_candidates(f)}
            gold_file_nodes = {n for n in g.ids if node_file(n, fm)}
            row.update(has_ident=info["anchors_from_ident"],
                       sym={k: outcome(v, gold.symbols, g.nodes) for k, v in lists.items()} if gold.symbols else {},
                       file={k: outcome(v, gold_file_nodes, g.nodes) for k, v in lists.items()},
                       hop=hop_distance(info["anchors"], gold.symbols, g.adj) if gold.symbols else None)
        rows.append(row)
    return rows


def _ci(v: np.ndarray, p: Params) -> list[float]:
    m, lo, hi = bootstrap_ci(v, p.n_boot, p.seed)
    return [round(m, 4), round(lo, 4), round(hi, 4)]  # rounded ONCE more only at display time


def summarize(rows: list[dict], level: str, p: Params) -> dict:
    sel = [r for r in rows if r.get(level)]
    if not sel:
        return {"n": 0}
    out = {"n": len(sel)}
    for s in SIGNALS:
        oc = [r[level][s] for r in sel]
        toks_hit = [o["tokens"] for o in oc if o["tokens"] is not None]
        out[s] = {**{f"R@{k}": _ci(hits_at(oc, k), p) for k in KS},
                  "MRR": _ci(rr(oc), p),
                  **{f"Hit@{b // 1000}k_tok": _ci(hits_within_budget(oc, b), p) for b in BUDGETS_TOKENS},
                  "median_tokens_to_hit": int(np.median(toks_hit)) if toks_hit else None}
    return out


def _metric_fn(metric: str):
    """'R@k' -> hit within top-k; 'Hit@Nk_tok' -> hit within N thousand tokens of reading."""
    if metric.startswith("R@"):
        k = int(metric[2:])
        return lambda oc: hits_at(oc, k)
    if metric.startswith("Hit@") and metric.endswith("k_tok"):
        b = int(metric[4:-5]) * 1000
        return lambda oc: hits_within_budget(oc, b)
    raise ValueError(metric)


def paired_family(sel: list[dict], p: Params, metric: str, primary: str = PRIMARY,
                  others: tuple[str, ...] | None = None) -> dict:
    """Primary vs each other signal on the same tasks: paired bootstrap Δ, exact McNemar, Holm across the family."""
    if not sel:
        return {}
    fn = _metric_fn(metric)
    a = fn([r["sym"][primary] for r in sel])
    res, ps = {}, {}
    for s in (others or tuple(x for x in SIGNALS if x != primary)):
        b = fn([r["sym"][s] for r in sel])
        pb = paired_bootstrap(a, b, p.n_boot, p.seed)
        mc = mcnemar_exact(a, b)
        res[s] = {"diff": round(pb["diff"], 4), "ci": [round(pb["lo"], 4), round(pb["hi"], 4)],
                  "mcnemar_p": round(mc["p"], 4), "primary_only": mc["a_only"], "other_only": mc["b_only"], "n": len(sel)}
        ps[s] = mc["p"]
    for s, adj in holm(ps).items():
        res[s]["mcnemar_p_holm"] = round(adj, 4)
    return res


def comparisons(rows: list[dict], p: Params) -> dict:
    """Paired comparisons (symbol level), each dict one Holm family. RRF+ vs others at R@5/R@20 was fixed in advance;
    the Hit@8k_tok and anchor-free (no_anchor_*) families were added after inspecting descriptive results (post hoc)."""
    sel = [r for r in rows if r.get("sym")]
    no_anchor = [r for r in sel if not r.get("has_ident")]
    return {
        f"{PRIMARY}_vs_others_R@5": paired_family(sel, p, "R@5"),
        f"{PRIMARY}_vs_others_R@20": paired_family(sel, p, "R@20"),
        # reading budget: does fusion's rank advantage survive a token budget?
        f"{PRIMARY}_vs_others_Hit@8k_tok": paired_family(sel, p, "Hit@8k_tok"),
        # anchor-free mode: does fusion dilute the lexical signal?
        "no_anchor_bm25_vs_fusion_R@50": paired_family(no_anchor, p, "R@50", primary="bm25", others=("rrf", "rrf+")),
        "no_anchor_bm25_vs_fusion_R@20": paired_family(no_anchor, p, "R@20", primary="bm25", others=("rrf", "rrf+")),
    }


def provenance(data_dir: Path, p: Params) -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10,
                                  cwd=Path(__file__).resolve().parent).stdout.strip()
        except OSError:
            return None
    return {"schema_version": SCHEMA_VERSION, "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
            "python": sys.version.split()[0], "numpy": np.__version__, "platform": platform.platform(),
            "params": asdict(p), "data": manifest(data_dir)}


def run(data_dir: Path, out_dir: Path, p: Params = Params(), log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = per_task(data_dir, p, log)
    (out_dir / "private").mkdir(exist_ok=True)
    (out_dir / "private" / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    src = [r for r in rows if r["source_change"]]
    checked = sum(r["header_checked"] for r in rows)
    summary = {
        "provenance": provenance(data_dir, p),
        "coverage": {"tasks": len(rows), "source_change": len(src), "with_gold_symbol": sum(bool(r.get("sym")) for r in rows),
                     "hunks_total": sum(r["hunks_total"] for r in rows), "hunks_mapped": sum(r["hunks_mapped"] for r in rows),
                     "label_header_agreement": [sum(r["header_agree"] for r in rows), checked,
                                                round(sum(r["header_agree"] for r in rows) / checked, 3) if checked else None],
                     "label_full_coverage": [sum(r["edit_full_cov"] for r in rows), sum(r["edit_hunks"] for r in rows)],
                     "issue_names_resolvable_symbol": sum(bool(r.get("has_ident")) for r in src),
                     "by_type": {t: sum(r["type"] == t for r in src) for t in ("bug", "feature", "other")},
                     "by_repo": {repo: sum(r["repo"] == repo for r in src) for repo in sorted({r["repo"] for r in src})}},
        "symbol_level": summarize(rows, "sym", p),
        "file_level": summarize(rows, "file", p),
        "by_anchor": {"named_symbol": summarize([r for r in rows if r.get("has_ident")], "sym", p),
                      "no_named_symbol": summarize([r for r in rows if r.get("source_change") and not r.get("has_ident")], "sym", p)},
        "by_type": {t: summarize([r for r in rows if r["type"] == t], "sym", p) for t in ("bug", "feature", "other")},
        "by_repo": {repo: summarize([r for r in rows if r["repo"] == repo], "sym", p)
                    for repo in sorted({r["repo"] for r in src})},
        "hop_distance": {str(k): v for k, v in sorted(
            Counter(r["hop"] for r in rows if r.get("sym")).items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
        "comparisons": comparisons(rows, p),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def sensitivity(data_dir: Path, out_dir: Path, base: Params = Params(), log=print) -> dict:
    """One-at-a-time variation of the pre-registered parameters; reports R@5/R@20/MRR point estimates."""
    grid = {"rrf_k": [10, 30, 60, 100], "n_anchors": [1, 3, 5], "bm25": [(0.9, 0.4), (1.2, 0.75), (1.5, 0.9)],
            "gold_min_cov": [0.01, 0.5, 1.0]}
    res = {}
    for name, values in grid.items():
        for v in values:
            p = (Params(**{**asdict(base), "bm25_k1": v[0], "bm25_b": v[1]}) if name == "bm25"
                 else Params(**{**asdict(base), name: v}))
            rows = per_task(data_dir, p, log=lambda *_: None)
            sel = [r for r in rows if r.get("sym")]
            entry = {}
            for s in ("bm25", "rrf", "rrf+"):
                oc = [r["sym"][s] for r in sel]
                entry[s] = {"R@5": round(float(hits_at(oc, 5).mean()), 3), "R@20": round(float(hits_at(oc, 20).mean()), 3),
                            "MRR": round(float(rr(oc).mean()), 3)}
            entry["n"] = len(sel)
            res[f"{name}={v}"] = entry
            log(f"sensitivity {name}={v}: rrf+ R@5 {entry['rrf+']['R@5']}")
    (out_dir / "sensitivity.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res

# ======== analysis/llm_v2.py ========
# ---- kernel tail, appended after the inlined locstudy modules by kernels/build_v2.py ----
# Model-in-the-loop localization (Gemma 4 31B QAT, temperature 0, thinking off), same labels/signals as the study.
#   hyp        : model proposes up to 10 fully-qualified symbols from the issue + module list -> resolved like the harness
#   hyp_fused  : RRF of hyp, Identifiers+, BM25, embedding neighbours and 2-hop graph of hyp anchors
#   rerank50   : model re-orders BM25's top-50 (id + signature + docstring line)
#   policy     : the paper's two-mode rule — RRF+ when the issue names a resolvable symbol, else rerank50
# Outputs (/kaggle/working): llm_rows.jsonl (per-task outcomes, same schema as the study), llm_raw.jsonl (raw model
# outputs, private), llm_meta.json (model, prompt hashes, vLLM args, parse/latency/token statistics).
import concurrent.futures as _cf
import time
import hashlib as _hl
import os as _os
import subprocess as _sp
import requests as _rq

KDATA = Path("/kaggle/input/competitions/gemma-4-developer-agent")
WORKDIR = Path("/kaggle/working")
API = "http://127.0.0.1:8000/v1"
SERVED = "gemma4"
VLLM_ARGS = ["--tensor-parallel-size", "{tp}", "--max-model-len", "16384", "--gpu-memory-utilization", "0.80",
             "--max-num-seqs", "16", "--reasoning-parser", "gemma4"]
SYSTEM = "You localize bugs in Python repositories. Reply with one JSON object only."
P_HYP = ("Repository: {repo}\nModules (most common first): {modules}\n\nIssue:\n{issue}\n\n"
         "List up to 10 fully-qualified symbols (module.Class.method or module.function) in this repository that most "
         'likely must be edited to resolve the issue, best first. JSON: {{"symbols": ["..."]}}')
P_RERANK = ("Issue:\n{issue}\n\nCandidate symbols:\n{listing}\n\nReturn the 10 candidates most likely to need editing to "
            'resolve the issue, best first, by their numbers. JSON: {{"ranking": [numbers]}}')
PROMPT_SHA = _hl.sha256((SYSTEM + P_HYP + P_RERANK).encode()).hexdigest()[:16]


def chat(user: str, max_tokens: int) -> dict:
    body = {"model": SERVED, "temperature": 0.0, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    t0, err = time.perf_counter(), None
    for attempt in range(4):
        try:
            r = _rq.post(f"{API}/chat/completions", json=body, timeout=600)
            if r.status_code == 400 and "response_format" in body:
                body.pop("response_format")
                continue
            r.raise_for_status()
            d = r.json()
            u = d.get("usage") or {}
            return {"text": d["choices"][0]["message"].get("content") or "", "latency": time.perf_counter() - t0,
                    "prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
                    "error": None}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:200]}"
            time.sleep(5 * (attempt + 1))
    return {"text": "", "latency": time.perf_counter() - t0, "prompt_tokens": 0, "completion_tokens": 0, "error": err}


def parse_obj(s: str) -> dict | None:
    for cand in (s, (re.search(r"\{.*\}", s, re.S) or [None])[0] if s else None):
        if not cand:
            continue
        try:
            o = json.loads(cand)
            return o if isinstance(o, dict) else None
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def signature(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sig = lines[0][:140] if lines else ""
    doc = next((l.strip("\"' ") for l in lines[1:4] if l.startswith(('"""', "'''", '"', "'"))), "")
    return sig + (f"  # {doc[:100]}" if doc else "")


def module_list(ids: list[str], limit: int = 200) -> str:
    return ", ".join(m for m, _ in Counter(".".join(n.split(".")[:2]) for n in ids if "." in n).most_common(limit))


def one_task(t: Task, p: Params) -> tuple[dict, dict]:
    g = load_graph(str(KDATA), t.graph_key, p.bm25_k1, p.bm25_b)
    gold = gold_for(t.patch, g.nodes, p.gold_min_cov)
    lists, g, info = rankings(t, str(KDATA), p)
    issue = t.problem_statement
    h = chat(P_HYP.format(repo=t.repo, modules=module_list(g.ids), issue=issue[:6000]), 600)
    ho = parse_obj(h["text"]) or {}
    hyps = [s for s in (ho.get("symbols") or []) if isinstance(s, str)][:10]
    r_hyp = g.index.rank(hyps)
    anchors = (r_hyp or lists["ident+"] or lists["bm25"])[: p.n_anchors]
    hyp_fused = rrf([r_hyp, lists["ident+"], lists["bm25"], g.neighbors_by_embedding(anchors), expand(anchors, g.adj, 2)], k=p.rrf_k)
    cands = lists["bm25"][:50]
    listing = "\n".join(f"{i}. {c} :: {signature(g.nodes[c])}" for i, c in enumerate(cands))
    rr_ = chat(P_RERANK.format(issue=issue[:5000], listing=listing), 300) if cands else {"text": "", "latency": 0,
                                                                                         "prompt_tokens": 0, "completion_tokens": 0, "error": None}
    ro = parse_obj(rr_["text"]) or {}
    order = [cands[i] for i in (ro.get("ranking") or []) if isinstance(i, int) and 0 <= i < len(cands)]
    rerank50 = list(dict.fromkeys(order + lists["bm25"]))
    policy = lists["rrf+"] if info["anchors_from_ident"] else rerank50
    new = {"hyp": r_hyp, "hyp_fused": hyp_fused, "rerank50": rerank50, "policy": policy}
    row = {"id": t.instance_id, "repo": t.repo, "has_ident": info["anchors_from_ident"], "n_gold": len(gold.symbols),
           "sym": {k: outcome(v, gold.symbols, g.nodes) for k, v in {**lists, **new}.items()},
           "llm": {"hyp_parsed": "symbols" in ho, "hyp_n": len(hyps), "hyp_resolved": bool(r_hyp),
                   "rerank_parsed": "ranking" in ro, "rerank_valid": len(order),
                   "latency_s": round(h["latency"] + rr_["latency"], 2),
                   "prompt_tokens": h["prompt_tokens"] + rr_["prompt_tokens"],
                   "completion_tokens": h["completion_tokens"] + rr_["completion_tokens"],
                   "errors": [e for e in (h["error"], rr_["error"]) if e]}}
    raw = {"id": t.instance_id, "hyp_text": h["text"][:4000], "rerank_text": rr_["text"][:2000]}
    return row, raw


def start_vllm() -> dict:
    whl_dir = Path("/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse")
    tmp = Path("/tmp/wheelhouse"); tmp.mkdir(parents=True, exist_ok=True)
    for w in whl_dir.glob("*.whl"):
        if "cutlass" in w.name.lower():
            continue
        name = w.name.replace("cu128", "+cu128") if ("cu128" in w.name and "+" not in w.name) else w.name
        if not (tmp / name).exists():
            _os.symlink(w, tmp / name)
    _sp.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--force-reinstall",
             *sorted(str(w) for w in tmp.glob("*.whl"))], check=True)
    import torch
    n = torch.cuda.device_count()
    tp = 4 if n >= 4 else (2 if n >= 2 else 1)
    args = [a.format(tp=tp) for a in VLLM_ARGS]
    model_path = "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"
    env = dict(_os.environ, VLLM_WORKER_MULTIPROC_METHOD="spawn", VLLM_NO_USAGE_STATS="1",
               PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", VLLM_ENGINE_READY_TIMEOUT_S="1200")
    log = open(WORKDIR / "vllm.log", "w")
    proc = _sp.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", model_path,
                      "--served-model-name", SERVED, "--host", "127.0.0.1", "--port", "8000", *args],
                     stdout=log, stderr=_sp.STDOUT, env=env)
    for i in range(240):
        if proc.poll() is not None:
            break
        try:
            if _rq.get(f"{API}/models", timeout=5).ok:
                print(f"vLLM ready after {i * 5}s, gpus={n}, tp={tp}", flush=True)
                return {"gpus": n, "tp": tp, "args": args, "model_path": model_path}
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    log.flush()
    print((WORKDIR / "vllm.log").read_text(errors="replace")[-5000:], flush=True)
    raise RuntimeError("vLLM did not start")


def main_llm(workers: int = 8) -> None:
    t_start = time.perf_counter()
    meta = {"prompt_sha": PROMPT_SHA, "vllm": start_vllm(), "params": asdict(Params())}
    p = Params()
    tasks = [t for t in load_tasks(KDATA)]
    keep = []
    for t in tasks:  # only tasks with gold symbols, same rule as the study
        g = load_graph(str(KDATA), t.graph_key, p.bm25_k1, p.bm25_b)
        if gold_for(t.patch, g.nodes, p.gold_min_cov).symbols:
            keep.append(t)
    print(f"{len(keep)} tasks with gold symbols", flush=True)
    rows, raws = [], []
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one_task, t, p): t.instance_id for t in keep}
        for i, f in enumerate(_cf.as_completed(futs)):
            try:
                row, raw = f.result()
                rows.append(row); raws.append(raw)
            except Exception as e:  # noqa: BLE001 - one failing task must not kill the run
                rows.append({"id": futs[f], "error": f"{type(e).__name__}: {e}"[:300]})
            if i % 10 == 0:
                print(f"[{i}/{len(keep)}] {time.perf_counter() - t_start:.0f}s", flush=True)
    rows.sort(key=lambda r: r["id"]); raws.sort(key=lambda r: r["id"])
    ok = [r for r in rows if "sym" in r]
    meta.update(n_tasks=len(keep), n_ok=len(ok), wall_s=round(time.perf_counter() - t_start, 1),
                hyp_parse_rate=round(float(np.mean([r["llm"]["hyp_parsed"] for r in ok])), 4) if ok else None,
                rerank_parse_rate=round(float(np.mean([r["llm"]["rerank_parsed"] for r in ok])), 4) if ok else None,
                hyp_resolved_rate=round(float(np.mean([r["llm"]["hyp_resolved"] for r in ok])), 4) if ok else None,
                mean_latency_s=round(float(np.mean([r["llm"]["latency_s"] for r in ok])), 2) if ok else None,
                tokens=int(sum(r["llm"]["prompt_tokens"] + r["llm"]["completion_tokens"] for r in ok)))
    (WORKDIR / "llm_rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (WORKDIR / "llm_raw.jsonl").write_text("\n".join(json.dumps(r) for r in raws) + "\n", encoding="utf-8")
    (WORKDIR / "llm_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1), flush=True)


if __name__ == "__main__":
    main_llm()
