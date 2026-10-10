"""How well do the harness' code-intelligence signals localize the code that the reference fix edits?

For every dev task: derive gold symbols from the reference `patch` (graph nodes whose source contains the
changed lines), then rank all graph nodes with each signal using ONLY the issue text, and report
Recall@k / MRR at symbol and file level. No GPU, no LLM: pure measurement of retrieval signals.

Signals
  ident  identifiers extracted from the issue, resolved like the harness (exact -> suffix -> case-insens. -> substring)
  bm25   BM25 over node id + source text, query = issue text
  emb    cosine neighbours (pre-computed node embeddings) of the top anchors (ident, else bm25)
  graph  1-hop call-graph neighbours of the top anchors
  rrf    reciprocal-rank fusion of the four lists
Run: python analysis/localization.py   (expects data/ from scripts/fetch_data.sh)
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KS = (1, 5, 10, 20, 50)
STOP = set("""a an the and or of to in on for with is are be was were it this that as by at from not no can
could should would will may might do does did has have had i we you they he she my our your if then else when
but so use using used get set add new return true false none self cls def class import from print len list dict
str int float bool type object value values key keys item items error errors issue bug fix feature support
example code test tests python version file files function method""".split())
_SPLIT = re.compile(r"[A-Za-z][a-z0-9]*|[0-9]+")


def toks(s: str) -> list[str]:
    return [t.lower() for t in _SPLIT.findall(s.replace("_", " ")) if t.lower() not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.tf = [Counter(d) for d in docs]
        self.ln = np.array([len(d) for d in docs], dtype=float)
        self.avg = self.ln.mean() if len(docs) else 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, q):
        q = [t for t in set(q) if t in self.idf]
        out = np.zeros(len(self.tf))
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.ln[i] / self.avg))
            out[i] = s
        return out


# ---------------- gold symbols from the reference patch ----------------
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(patch: str) -> dict[str, list[dict]]:
    files, cur, hunk = {}, None, None
    for line in patch.splitlines():
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            cur = path[2:] if path.startswith("b/") else path
            files.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            hunk = {"removed": [], "context": [], "added": []}
            files[cur].append(hunk)
        elif hunk is not None and cur:
            if line.startswith("-"):
                hunk["removed"].append(line[1:])
            elif line.startswith("+"):
                hunk["added"].append(line[1:])
            elif line.startswith(" "):
                hunk["context"].append(line[1:])
    return files


def is_source(path: str) -> bool:
    p = path.lower()
    return p.endswith(".py") and not re.search(r"(^|/)(tests?|testing|docs|docs_src)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$", p)


def module_candidates(path: str) -> list[str]:
    """Dotted module names a file may appear under in node ids (docs_src/ and src/ prefixes are dropped).
    Single-component suffixes are kept only for top-level files, to avoid spurious matches."""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    cands = [".".join(parts[i:]) for i in range(len(parts)) if len(parts[i:]) >= 2 or len(parts) == 1]
    return cands or [".".join(parts)]


def is_init(path: str) -> bool:
    return path.endswith("__init__.py")


def node_file(nid: str, file_modules: dict[str, str]) -> str | None:
    """Gold file a node belongs to. Package __init__ files only own their direct children."""
    best = None
    for mod, f in file_modules.items():
        if not (nid == mod or nid.startswith(mod + ".")):
            continue
        if is_init(f) and nid.count(".") != mod.count(".") + 1:
            continue
        if best is None or len(mod) > len(best[0]):
            best = (mod, f)
    return best[1] if best else None


def gold_symbols(files: dict, nodes: dict[str, str]) -> tuple[set[str], set[str]]:
    gold, gold_files = set(), set()
    for path, hunks in files.items():
        if not is_source(path):
            continue
        gold_files.add(path)
        mods = module_candidates(path)
        cands = {nid: txt for nid, txt in nodes.items() if any(nid.startswith(m + ".") for m in mods)}
        for h in hunks:
            removed = [l.strip() for l in h["removed"] if len(l.strip()) >= 4]
            ctx = [l.strip() for l in h["context"] if len(l.strip()) >= 4]
            hits = []
            for nid, txt in cands.items():
                lines = {l.strip() for l in txt.splitlines()}
                r = sum(1 for l in removed if l in lines)
                c = sum(1 for l in ctx if l in lines)
                if r >= 1 or (not removed and c >= 2):
                    hits.append((r, c, -len(txt), nid))
            if hits:
                hits.sort(reverse=True)
                top = hits[0]
                gold.add(top[3])
    return gold, gold_files


# ---------------- signals ----------------
_IDENT = [re.compile(p) for p in (r"`([^`\n]{2,80})`", r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b",
                                  r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b", r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b",
                                  r"\b([A-Za-z_]\w{2,})\(")]


def extract_identifiers(text: str) -> list[str]:
    seen = Counter()
    for rx in _IDENT:
        for m in rx.finditer(text):
            tok = m.group(1).strip().strip("()").split("(")[0]
            for t in re.split(r"[\s,]+", tok):
                t = t.strip(".:;'\"")
                if len(t) >= 3 and t.lower() not in STOP and not t.isdigit():
                    seen[t] += 1
    return [t for t, _ in seen.most_common()]


def resolve(tok: str, ids: list[str], last: dict[str, list[str]]) -> list[tuple[int, str]]:
    if tok in last.get("__all__", ()):  # exact id
        return [(0, tok)]
    out = []
    tail = tok.split(".")[-1]
    for nid in last.get(tail, []):
        if nid.endswith("." + tok) or nid == tok or nid.split(".")[-1] == tok:
            out.append((1, nid))
    if out:
        return out
    low = tail.lower()
    out = [(2, nid) for nid in last.get("__lower__" + low, [])]
    if out or len(tail) < 5:
        return out
    return [(3, nid) for nid in ids if low in nid.split(".")[-1].lower()][:50]


def rank_ident(issue: str, ids: list[str], index: dict) -> list[str]:
    scored = defaultdict(float)
    for pos, tok in enumerate(extract_identifiers(issue)[:40]):
        hits = resolve(tok, ids, index)
        if not hits:
            continue
        w = 1.0 / (1 + math.log1p(len(hits))) / (1 + 0.05 * pos)
        for tier, nid in hits:
            scored[nid] += w * (1.0, 0.8, 0.5, 0.2)[tier]
    return [n for n, _ in sorted(scored.items(), key=lambda x: -x[1])]


def rrf(lists: list[list[str]], k: int = 60) -> list[str]:
    s = defaultdict(float)
    for lst in lists:
        for r, n in enumerate(lst[:200]):
            s[n] += 1.0 / (k + r + 1)
    return [n for n, _ in sorted(s.items(), key=lambda x: -x[1])]


def metrics(ranked: list[str], gold: set[str]) -> dict:
    out = {f"R@{k}": float(bool(gold & set(ranked[:k]))) for k in KS}
    rr = next((1.0 / (i + 1) for i, n in enumerate(ranked) if n in gold), 0.0)
    out["MRR"] = rr
    return out


def run() -> dict:
    tasks = [json.loads(l) for l in (DATA / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if l]
    per_signal = defaultdict(list)
    per_signal_file = defaultdict(list)
    coverage = Counter()
    cache = {}
    t0 = time.perf_counter()
    for ti, t in enumerate(tasks):
        if ti % 10 == 0:
            print(f"[{ti}/{len(tasks)}] {time.perf_counter() - t0:.0f}s", file=sys.stderr, flush=True)
        short = t["repo"].split("/")[1].lower()
        key = f"{short}_{t['base_commit']}"
        if key not in cache:
            g = json.loads((DATA / "graphs" / f"{key}.json").read_text(encoding="utf-8"))
            z = np.load(DATA / "embeddings" / f"{key}.npz", allow_pickle=False)
            nodes = {n["id"]: n.get("text") or "" for n in g["nodes"]}
            ids = list(nodes)
            emb = np.stack([z[i] for i in ids]).astype(np.float32)
            emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
            adj = defaultdict(set)
            for e in g["edges"]:
                adj[e["source"]].add(e["target"]); adj[e["target"]].add(e["source"])
            index = {"__all__": set(ids)}
            for nid in ids:
                tail = nid.split(".")[-1]
                index.setdefault(tail, []).append(nid)
                index.setdefault("__lower__" + tail.lower(), []).append(nid)
            bm = BM25([toks(nid.replace(".", " ")) * 2 + toks(nodes[nid]) for nid in ids])
            cache = {key: (nodes, ids, emb, adj, index, bm)}  # keep one graph in memory
        nodes, ids, emb, adj, index, bm = cache[key]
        gold, gold_files = gold_symbols(parse_patch(t["patch"]), nodes)
        coverage["tasks"] += 1
        coverage["with_source_change"] += bool(gold_files)
        coverage["with_gold_symbol"] += bool(gold)
        if not gold_files:
            continue
        issue = t["problem_statement"]
        r_ident = rank_ident(issue, ids, index)
        sc = bm.scores(toks(issue))
        r_bm25 = [ids[i] for i in np.argsort(-sc)[:500] if sc[i] > 0]
        anchors = (r_ident or r_bm25)[:3]
        if anchors:
            idx = {n: i for i, n in enumerate(ids)}
            sims = emb @ emb[[idx[a] for a in anchors]].T
            r_emb = [ids[i] for i in np.argsort(-sims.max(axis=1))[:500]]
            r_graph = [n for a in anchors for n in [a, *sorted(adj.get(a, ()))]]
        else:
            r_emb, r_graph = [], []
        r_graph = list(dict.fromkeys(r_graph))
        lists = {"ident": r_ident, "bm25": r_bm25, "emb": r_emb, "graph": r_graph,
                 "rrf": rrf([r_ident, r_bm25, r_emb, r_graph])}
        file_modules = {m: f for f in gold_files for m in module_candidates(f)}
        coverage["issue_has_resolvable_identifier"] += bool(r_ident)
        for name, ranked in lists.items():
            if gold:
                per_signal[name].append(metrics(ranked, gold))
            # file-level: rank of the first node that lives in a gold file
            hit_rank = next((i for i, n in enumerate(ranked) if node_file(n, file_modules)), None)
            per_signal_file[name].append({f"R@{k}": float(hit_rank is not None and hit_rank < k) for k in KS}
                                         | {"MRR": 1.0 / (hit_rank + 1) if hit_rank is not None else 0.0})
    agg = lambda rows: {m: round(float(np.mean([r[m] for r in rows])), 3) for m in rows[0]} if rows else {}  # noqa: E731
    return {"coverage": dict(coverage),
            "symbol_level": {k: agg(v) | {"n": len(v)} for k, v in per_signal.items()},
            "file_level": {k: agg(v) | {"n": len(v)} for k, v in per_signal_file.items()}}


if __name__ == "__main__":
    res = run()
    out = ROOT / "analysis" / "localization_results.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
