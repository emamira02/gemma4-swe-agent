"""Post hoc anchor analyses registered in docs/posthoc-anchor-analysis-2026-11-02.md (Q1-Q3), on the 114 tasks.

    python -m analysis.anchor_posthoc [--out results/anchor_posthoc.json]

Inputs: results/kaggle_v2/llm_rows.jsonl (per-task ranks of BM25, RRF+ and the re-rank; anchor status) and, for the
lexical-overlap covariate only, data/tasks.jsonl + data/graphs (read locally; the output keeps aggregates only).
Q1 anchor gap per method and its change under the re-rank; Q2 the re-rank's gap split into pool reachability and
ranking given reachability; Q3 logistic regression Hit@5 ~ anchored + standardised overlap, odds ratio of anchored.
Intervals: bootstrap with tasks resampled within each stratum (sizes fixed), percentile 95 %.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from analysis.failure_audit import ROOT
from locstudy.data import load_tasks
from locstudy.gold import gold_for
from locstudy.signals import toks

METHODS = ("bm25", "rrf+", "rerank50")
POOL = 50  # the re-rank re-orders BM25's top 50, so its top 5 can only hold what that pool holds


def _hit(r: dict, m: str, k: int) -> float:
    rank = r["sym"][m]["rank"]
    return float(rank is not None and rank < k)


def overlap(issue: str, gold: set[str], nodes: dict[str, str]) -> float:
    """Share of the issue's distinct terms that occur in the ids or source of the gold symbols (uses gold: retrospective)."""
    terms = set(toks(issue))
    if not terms:
        return 0.0
    g = set().union(*(toks(n.replace(".", " ")) + toks(nodes.get(n, "")) for n in gold)) if gold else set()
    return len(terms & g) / len(terms)


def logit(x: np.ndarray, y: np.ndarray, iters: int = 50) -> np.ndarray | None:
    """Maximum-likelihood logistic regression by Newton steps; None when it does not converge (e.g. separation)."""
    beta = np.zeros(x.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-x @ beta))
        w = p * (1 - p)
        h = x.T @ (x * w[:, None]) + 1e-9 * np.eye(x.shape[1])
        step = np.linalg.solve(h, x.T @ (y - p))
        beta += step
        if not np.all(np.isfinite(beta)) or np.abs(beta).max() > 15:
            return None
        if np.abs(step).max() < 1e-10:
            return beta
    return None


def decompose(ra: float, ca: float, rf: float, cf: float) -> tuple[float, float]:
    """Shapley split of ra*ca - rf*cf into the reachability and the ranking factor (the two parts sum to the gap)."""
    return (ra - rf) * (ca + cf) / 2, (ca - cf) * (ra + rf) / 2


def stats(h5: dict[str, np.ndarray], reach: np.ndarray, anch: np.ndarray, z: np.ndarray) -> dict:
    a, f = anch, ~anch
    gap = {m: h5[m][a].mean() - h5[m][f].mean() for m in METHODS}
    ra, rf = reach[a].mean(), reach[f].mean()
    ca = h5["rerank50"][a & reach].mean() if (a & reach).any() else np.nan
    cf = h5["rerank50"][f & reach].mean() if (f & reach).any() else np.nan
    c_r, c_c = decompose(ra, ca, rf, cf)
    x = np.column_stack([np.ones(len(z)), anch.astype(float), z])
    fits = {m: logit(x, h5[m]) for m in METHODS}
    return {"gap": gap, "gap_minus_rerank": {b: gap[b] - gap["rerank50"] for b in ("bm25", "rrf+")},
            "R": {"anchored": ra, "anchor_free": rf}, "C": {"anchored": ca, "anchor_free": cf},
            "contrib": {"reachability": c_r, "ranking": c_c},
            "share_reachability": c_r / gap["rerank50"] if gap["rerank50"] > 0 else np.nan,
            "or_anchored": {m: float(np.exp(b[1])) if b is not None else np.nan for m, b in fits.items()},
            "or_overlap_sd": {m: float(np.exp(b[2])) if b is not None else np.nan for m, b in fits.items()}}


def _walk(d: dict, path=()):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _walk(v, (*path, k))
        else:
            yield (*path, k), v


def analyze(rows: list[dict], ov: np.ndarray, n_boot: int = 10_000, seed: int = 0) -> dict:
    anch = np.array([bool(r["has_ident"]) for r in rows])
    h5 = {m: np.array([_hit(r, m, 5) for r in rows]) for m in METHODS}
    reach = np.array([_hit(r, "bm25", POOL) for r in rows]).astype(bool)
    z = (ov - ov.mean()) / ov.std()
    point = stats(h5, reach, anch, z)
    ia, iff = np.flatnonzero(anch), np.flatnonzero(~anch)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        idx = np.concatenate([rng.choice(ia, ia.size), rng.choice(iff, iff.size)])
        boots.append(stats({m: v[idx] for m, v in h5.items()}, reach[idx], anch[idx], z[idx]))
    out, failed = {}, {}
    for path, v in _walk(point):
        draws = np.array([float(_get(b, path)) for b in boots])
        ok = draws[np.isfinite(draws)]
        lo, hi = np.quantile(ok, [0.025, 0.975]) if ok.size else (np.nan, np.nan)
        _set(out, path, [round(float(v), 4), round(float(lo), 4), round(float(hi), 4)])
        if ok.size < n_boot:
            _set(failed, path, int(n_boot - ok.size))
    by_repo: dict = {}  # added after Q1-Q3 (addendum in the registration note): descriptive, not registered
    for r, a in zip(rows, anch):
        cell = by_repo.setdefault(r.get("repo", "?"), {}).setdefault("anchored" if a else "anchor_free", {"n": 0, **dict.fromkeys(METHODS, 0)})
        cell["n"] += 1
        for m in METHODS:
            cell[m] += int(_hit(r, m, 5))
    for cells in by_repo.values():
        for cell in cells.values():
            cell.update({f"{m}_rate": round(cell[m] / cell["n"], 4) for m in METHODS})
    return {"registered": "docs/posthoc-anchor-analysis-2026-11-02.md", "status": "post hoc",
            "n": {"anchored": int(anch.sum()), "anchor_free": int((~anch).sum())},
            "params": {"n_boot": n_boot, "seed": seed, "pool": POOL, "k": 5},
            "overlap_mean": {"anchored": round(float(ov[anch].mean()), 4), "anchor_free": round(float(ov[~anch].mean()), 4)},
            **out, "unestimable_resamples": failed, "by_repo_hit5_unregistered": by_repo}


def _get(d: dict, path: tuple):
    for k in path:
        d = d[k]
    return d


def _set(d: dict, path: tuple, v) -> None:
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--rows", type=Path, default=ROOT / "results" / "kaggle_v2" / "llm_rows.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "anchor_posthoc.json")
    a = ap.parse_args()
    rows = [r for r in map(json.loads, a.rows.read_text(encoding="utf-8").splitlines()) if "sym" in r]
    tasks = {t.instance_id: t for t in load_tasks(a.data)}
    ov = []
    for r in rows:
        t = tasks[r["id"]]
        g = json.loads((a.data / "graphs" / f"{t.graph_key}.json").read_text(encoding="utf-8"))
        nodes = {n["id"]: n.get("text") or "" for n in g["nodes"]}
        gold = gold_for(t.patch, nodes).symbols
        if len(gold) != r["n_gold"]:
            raise ValueError(f"{r['id']}: {len(gold)} gold symbols here, {r['n_gold']} in the model run")
        ov.append(overlap(t.problem_statement, gold, nodes))
    doc = analyze(rows, np.array(ov))
    a.out.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    print(json.dumps(doc, indent=1))


if __name__ == "__main__":
    main()
