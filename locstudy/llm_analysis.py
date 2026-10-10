"""Analysis of the model-in-the-loop run (Kaggle kernel v2 output): CIs and pre-specified paired tests.

Input: results/kaggle_v2/llm_rows.jsonl + llm_meta.json. Output: results/llm_summary.json (no raw model text).
Pre-specified hypotheses (one Holm family each):
  H1 policy beats RRF+ and BM25 overall (R@5, R@20)
  H2 in anchor-free issues, rerank50 beats BM25 (R@5, R@20) and hyp_fused beats BM25 (R@5, R@20)
  H3 hyp_fused beats RRF+ overall (R@5)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .metrics import BUDGETS_TOKENS, KS, bootstrap_ci, hits_at, hits_within_budget, rr
from .study import Params, paired_family

NEW = ("hyp", "hyp_fused", "rerank50", "policy")
BASE = ("bm25", "rrf+")


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


def analyze(rows_path: Path, meta_path: Path, out_path: Path, p: Params = Params()) -> dict:
    rows = [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in rows if "sym" in r]
    failed = [r["id"] for r in rows if "sym" not in r]
    anch = [r for r in ok if r["has_ident"]]
    free = [r for r in ok if not r["has_ident"]]
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    res = {
        "meta": {k: meta.get(k) for k in ("prompt_sha", "n_tasks", "n_ok", "wall_s", "hyp_parse_rate", "rerank_parse_rate",
                                          "hyp_resolved_rate", "mean_latency_s", "tokens", "vllm")},
        "failed_tasks": failed,
        "all": block(ok, p), "named_symbol": block(anch, p), "no_named_symbol": block(free, p),
        "tests": {
            "H1_policy_R@5": paired_family(ok, p, "R@5", primary="policy", others=BASE),
            "H1_policy_R@20": paired_family(ok, p, "R@20", primary="policy", others=BASE),
            "H2_anchorfree_R@5": paired_family(free, p, "R@5", primary="bm25", others=("rerank50", "hyp_fused")),
            "H2_anchorfree_R@20": paired_family(free, p, "R@20", primary="bm25", others=("rerank50", "hyp_fused")),
            "H3_hypfused_R@5": paired_family(ok, p, "R@5", primary="hyp_fused", others=("rrf+",)),
        },
    }
    # H2 is stated as "new beats BM25": report deltas with the new signal as reference for readability
    for key in ("H2_anchorfree_R@5", "H2_anchorfree_R@20"):
        for s, r in res["tests"][key].items():
            r["diff_new_minus_bm25"] = round(-r["diff"], 4)
            r["ci_new_minus_bm25"] = [round(-r["ci"][1], 4), round(-r["ci"][0], 4)]
    out_path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res
