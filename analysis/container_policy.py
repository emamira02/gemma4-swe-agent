"""Offline check of the in-container localization policy (agent/skills/swe/scripts/localize.py) on the dev tasks.

The container has no graph or embeddings, so the agent's skill can only use identifiers, BM25 and literals.
On the graph's symbol set and the paper's strict gold labels this measures the policies the skill can implement:
  tokenizer  v1 = paper (ALL_CAPS words split into single letters and dropped)  v2 = camel/acronym-aware
  ident      loose = paper (case-insensitive / substring tiers for every token)  strict = plain lowercase words
             resolve only exactly
  policy     rrf([ident, bm25]) when identifiers resolve, else bm25 (the paper's mode rule)
Paired tests (exact McNemar, Holm within each metric) against the current skill (v1 + loose).
Run: python -m analysis.container_policy  ->  results/container_policy.json
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from locstudy.data import load_graph, load_tasks
from locstudy.gold import gold_for
from locstudy.metrics import bootstrap_ci, hits_at, holm, mcnemar_exact, outcome, paired_bootstrap
from locstudy.signals import BM25, STOP, SymbolIndex, extract_identifiers, rrf, toks
from locstudy.study import Params

ROOT = Path(__file__).resolve().parent.parent
_TRACE = re.compile(r'File "([^"]+?\.py)", line \d+, in (\w+)')
_PLAIN = re.compile(r"[a-z]+")
_SPLIT2 = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+[0-9]*|[A-Z]+[0-9]*|[0-9]+")


def toks2(s: str) -> list[str]:
    return [t.lower() for t in _SPLIT2.findall(s.replace("_", " ")) if t.lower() not in STOP and len(t) > 1]


class StrictIndex(SymbolIndex):
    def resolve(self, tok: str):
        hits = super().resolve(tok)
        return [h for h in hits if h[0] <= 1] if _PLAIN.fullmatch(tok) else hits


@lru_cache(maxsize=4)
def _extras(key: str):
    g = load_graph(str(ROOT / "data"), key)
    bm2 = BM25([toks2(n.replace(".", " ")) * 2 + toks2(g.nodes[n]) for n in g.ids])
    return bm2, StrictIndex(g.ids)


def policies(issue: str, g, key: str) -> dict[str, list[str]]:
    bm2, strict = _extras(key)
    idents = [fn for _, fn in _TRACE.findall(issue)] + extract_identifiers(issue)
    bm = {"v1": g.bm25.rank(toks(issue), g.ids), "v2": bm2.rank(toks2(issue), g.ids)}
    idl = {"loose": g.index.rank(idents), "strict": strict.rank(idents)}
    out = {f"bm25_{t}": bm[t] for t in bm}
    for t in bm:
        for i in idl:
            out[f"policy_{t}_{i}"] = rrf([idl[i], bm[t]]) if idl[i] else bm[t]
    return out


def main() -> None:
    p = Params()
    data = ROOT / "data"
    rows = []
    for t in sorted(load_tasks(data), key=lambda t: (t.graph_key, t.instance_id)):
        g = load_graph(str(data), t.graph_key, p.bm25_k1, p.bm25_b)
        gold = gold_for(t.patch, g.nodes, p.gold_min_cov)
        if gold.symbols:
            rows.append({k: outcome(v, gold.symbols, g.nodes) for k, v in policies(t.problem_statement, g, t.graph_key).items()})
    res = {"n": len(rows), "signals": {}, "tests": {}}
    for s in rows[0]:
        res["signals"][s] = {f"R@{k}": [round(x, 4) for x in bootstrap_ci(hits_at([r[s] for r in rows], k), p.n_boot, p.seed)]
                             for k in (1, 5, 10, 20, 50)}
    base = "policy_v1_loose"
    for k in (5, 20, 50):
        fam, ps = {}, {}
        a_ = hits_at([r[base] for r in rows], k)
        for s in ("policy_v1_strict", "policy_v2_loose", "policy_v2_strict"):
            b_ = hits_at([r[s] for r in rows], k)
            pb, mc = paired_bootstrap(b_, a_, p.n_boot, p.seed), mcnemar_exact(b_, a_)
            fam[s] = {"diff_vs_base": round(pb["diff"], 4), "ci": [round(pb["lo"], 4), round(pb["hi"], 4)],
                      "variant_only": mc["a_only"], "base_only": mc["b_only"], "p": round(mc["p"], 4)}
            ps[s] = mc["p"]
        for s, adj in holm(ps).items():
            fam[s]["p_holm"] = round(adj, 4)
        res["tests"][f"R@{k}"] = fam
    out = ROOT / "results" / "container_policy.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
