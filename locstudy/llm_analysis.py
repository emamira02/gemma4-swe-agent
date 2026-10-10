"""Analysis of the model-in-the-loop run (Kaggle kernel v2 output): CIs and pre-specified paired tests.

Input: results/kaggle_v2/llm_rows.jsonl + llm_meta.json. Output: results/llm_summary.json (no raw model text).
Pre-specified hypotheses (one Holm family each):
  H1 policy beats RRF+ and BM25 overall (R@5, R@20)
  H2 in anchor-free issues, rerank50 beats BM25 (R@5, R@20) and hyp_fused beats BM25 (R@5, R@20)
  H3 hyp_fused beats RRF+ overall (R@5)
Everything else (exploratory comparisons, re-rank ceiling, cost) is post hoc and reported as such, with Holm
correction across the exploratory family.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .metrics import BUDGETS_TOKENS, KS, bootstrap_ci, hits_at, hits_within_budget, holm, mcnemar_exact, paired_bootstrap, rr
from .study import Params, _metric_fn, paired_family

NEW = ("hyp", "hyp_fused", "rerank50", "policy")
BASE = ("bm25", "rrf+")
# pre-specified (committed before the model outputs were downloaded): name -> (block, metric, primary, others);
# each entry is one Holm family
HYPOTHESES = {
    "H1_policy_R@5": ("all", "R@5", "policy", BASE),
    "H1_policy_R@20": ("all", "R@20", "policy", BASE),
    "H2_anchorfree_R@5": ("no_named_symbol", "R@5", "bm25", ("rerank50", "hyp_fused")),
    "H2_anchorfree_R@20": ("no_named_symbol", "R@20", "bm25", ("rerank50", "hyp_fused")),
    "H3_hypfused_R@5": ("all", "R@5", "hyp_fused", ("rrf+",)),
}
RERANK_DEPTH = 50  # rerank50 re-orders BM25's top-50 and appends the rest of BM25 unchanged
# post hoc, after seeing H1-H3: (name, block, metric, a, b) -> a - b
EXPLORATORY = (
    ("rerank50_vs_rrf+_named_R@5", "named_symbol", "R@5", "rerank50", "rrf+"),
    ("rerank50_vs_policy_all_R@5", "all", "R@5", "rerank50", "policy"),
    ("rerank50_vs_bm25_all_Hit@8k_tok", "all", "Hit@8k_tok", "rerank50", "bm25"),
)
# candidate pools a re-ranker could be given (post hoc, descriptive): name -> ((signal, depth), ...), union of prefixes
POOLS = {"bm25@100": (("bm25", 100),), "bm25@50+hyp_fused@50": (("bm25", 50), ("hyp_fused", 50))}


def _in_top(r: dict, s: str, depth: int) -> bool:
    rank = r["sym"][s]["rank"]
    return rank is not None and rank < depth


def _ci(v, p: Params) -> list[float]:
    m, lo, hi = bootstrap_ci(v, p.n_boot, p.seed)
    return [round(m, 4), round(lo, 4), round(hi, 4)]


def block(rows: list[dict], p: Params) -> dict:
    out = {"n": len(rows)}
    if not rows:
        return out
    for s in (*BASE, *NEW):
        oc = [r["sym"][s] for r in rows]
        out[s] = {**{f"R@{k}": _ci(hits_at(oc, k), p) for k in KS}, "MRR": _ci(rr(oc), p),
                  **{f"Hit@{b // 1000}k_tok": _ci(hits_within_budget(oc, b), p) for b in BUDGETS_TOKENS}}
    return out


def exploratory(blocks: dict[str, list[dict]], p: Params) -> dict:
    """Post-hoc paired comparisons, Holm-corrected as one family (raw p-values, rounded only for storage)."""
    res, ps = {}, {}
    for name, key, metric, a, b in EXPLORATORY:
        sel = blocks[key]
        if not sel:
            continue
        fn = _metric_fn(metric)
        x, y = fn([r["sym"][a] for r in sel]), fn([r["sym"][b] for r in sel])
        pb, mc = paired_bootstrap(x, y, p.n_boot, p.seed), mcnemar_exact(x, y)
        res[name] = {"diff": round(pb["diff"], 4), "ci": [round(pb["lo"], 4), round(pb["hi"], 4)], "mcnemar_p": round(mc["p"], 4),
                     "a_only": mc["a_only"], "b_only": mc["b_only"], "n": len(sel)}
        ps[name] = mc["p"]
    for name, adj in holm(ps).items():
        res[name]["mcnemar_p_holm"] = round(adj, 4)
    return res


def ceiling(rows: list[dict], p: Params) -> dict:
    """Re-ranking can only promote what BM25's top-50 contains: reachability and re-rank recall given reachability."""
    out = {"n": len(rows)}
    if not rows:
        return out
    reach = [r for r in rows if _in_top(r, "bm25", RERANK_DEPTH)]
    out["reachable"] = _ci(np.array([_in_top(r, "bm25", RERANK_DEPTH) for r in rows], float), p)
    out["n_reachable"] = len(reach)
    out["pools"] = {name: _ci(np.array([any(_in_top(r, s, d) for s, d in spec) for r in rows], float), p)
                    for name, spec in POOLS.items()}
    if reach:
        oc = [r["sym"]["rerank50"] for r in reach]
        out.update({"R@1_given_reachable": _ci(hits_at(oc, 1), p), "R@5_given_reachable": _ci(hits_at(oc, 5), p)})
    return out


def cost(rows: list[dict]) -> dict:
    """Per-task model cost (two calls) and degraded outputs; latencies were measured under concurrent batching."""
    m = [r["llm"] for r in rows if "latency_s" in r.get("llm", {})]
    if not m:
        return {"n": 0}
    lat = np.array([x["latency_s"] for x in m], float)
    q = lambda v, f: round(float(np.quantile(v, f)), 2)  # noqa: E731
    return {"n": len(m), "latency_s_p50": q(lat, 0.5), "latency_s_p90": q(lat, 0.9), "latency_s_max": round(float(lat.max()), 2),
            "prompt_tokens_mean": round(float(np.mean([x["prompt_tokens"] for x in m])), 1),
            "completion_tokens_mean": round(float(np.mean([x["completion_tokens"] for x in m])), 1),
            "tokens_per_task_mean": round(float(np.mean([x["prompt_tokens"] + x["completion_tokens"] for x in m])), 1),
            "rerank_short": sum(x["rerank_valid"] < 10 for x in m), "hyp_unresolved": sum(not x["hyp_resolved"] for x in m),
            "errors": sum(bool(x["errors"]) for x in m)}


def analyze(rows_path: Path, meta_path: Path, out_path: Path, p: Params = Params()) -> dict:
    rows = [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in rows if "sym" in r]
    failed = [r["id"] for r in rows if "sym" not in r]
    anch = [r for r in ok if r["has_ident"]]
    free = [r for r in ok if not r["has_ident"]]
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    blocks = {"all": ok, "named_symbol": anch, "no_named_symbol": free}
    res = {
        "meta": {k: meta.get(k) for k in ("prompt_sha", "n_tasks", "n_ok", "wall_s", "hyp_parse_rate", "rerank_parse_rate",
                                          "hyp_resolved_rate", "mean_latency_s", "tokens", "vllm")},
        "failed_tasks": failed,
        **{k: block(v, p) for k, v in blocks.items()},
        "ceiling": {k: ceiling(v, p) for k, v in blocks.items()},
        "cost": cost(ok),
        "tests": {name: paired_family(blocks[b], p, m, primary=a, others=o) for name, (b, m, a, o) in HYPOTHESES.items()},
    }
    # H2 is stated as "new beats BM25": report deltas with the new signal as reference for readability
    for key in ("H2_anchorfree_R@5", "H2_anchorfree_R@20"):
        for s, r in res["tests"][key].items():
            r["diff_new_minus_bm25"] = round(-r["diff"], 4)
            r["ci_new_minus_bm25"] = [round(-r["ci"][1], 4), round(-r["ci"][0], 4)]
    res["exploratory"] = exploratory(blocks, p)
    out_path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res
