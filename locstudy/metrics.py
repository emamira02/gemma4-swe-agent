"""Per-task retrieval outcomes and task-level inference (bootstrap CIs, paired bootstrap, exact McNemar)."""
from __future__ import annotations

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
