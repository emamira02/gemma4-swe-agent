"""Task and repository-graph loading, plus a content manifest for provenance."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .signals import BM25, SymbolIndex, toks


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
