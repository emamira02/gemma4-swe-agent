"""End-to-end study: per-task outcomes for every signal, then aggregates with CIs, paired tests, sensitivity."""
from __future__ import annotations

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

from . import SCHEMA_VERSION
from .data import Task, load_graph, load_tasks, manifest
from .gold import gold_for, module_candidates, node_file
from .metrics import (BUDGETS_TOKENS, KS, bootstrap_ci, hits_at, hits_within_budget, holm, mcnemar_exact,
                      outcome, paired_bootstrap, rr)
from .signals import expand, extract_identifiers, extract_identifiers_plus, hop_distance, rrf, toks


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
    """Pre-specified paired comparisons (symbol level). Each dict is one Holm family."""
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
