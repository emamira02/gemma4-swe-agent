"""Ranking signals computed from the issue text only (no patch, no tests)."""
from __future__ import annotations

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
    from .gold import module_candidates
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
