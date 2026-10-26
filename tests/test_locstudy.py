"""Unit tests on synthetic fixtures only (no competition data needed, CI-safe)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from locstudy import data, gold, metrics, signals, study  # noqa: E402

PATCH = """diff --git a/pkg/core.py b/pkg/core.py
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -10,7 +10,7 @@ def parse_header(value):
     parts = value.split(";")
-    return parts[0]
+    return parts[0].strip()

@@ -40,3 +40,6 @@ class Client:
     def close(self):
         self.closed = True
+    def reset(self):
+        self.closed = False
diff --git a/tests/test_core.py b/tests/test_core.py
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -1,2 +1,3 @@ def test_x():
+    assert True
diff --git a/pkg/__init__.py b/pkg/__init__.py
--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,1 +1,2 @@
+from .core import parse_header
"""
NODES = {
    "pkg.core.parse_header": 'def parse_header(value):\n    """Split a header."""\n    parts = value.split(";")\n    return parts[0]',
    "pkg.core.other": "def other(value):\n    return parts[0]\n    x = 1",
    "pkg.core.Client": "class Client:\n    None",
    "pkg.core.Client.close": "def close(self):\n        self.closed = True",
    "pkg.util.helper": "def helper():\n    return parse_header('a')",
    "pkg.version": "VERSION = '1'",
}


def test_parse_patch_captures_headers_and_files():
    files = gold.parse_patch(PATCH)
    assert set(files) == {"pkg/core.py", "tests/test_core.py", "pkg/__init__.py"}
    h0, h1 = files["pkg/core.py"]
    assert h0.header == "def parse_header(value):" and h0.removed == ['    return parts[0]']
    assert h1.header == "class Client:" and len(h1.added) == 2 and not h1.removed


def test_gold_mapping_prefers_specific_node_and_skips_tests():
    g = gold.gold_for(PATCH, NODES)
    # hunk 1: 'return parts[0]' is in two nodes; 'parts = value.split(";")' context breaks the tie toward parse_header
    # hunk 2: pure addition, >=2 context lines inside Client.close
    assert g.symbols == {"pkg.core.parse_header", "pkg.core.Client.close"}
    assert g.files == {"pkg/core.py", "pkg/__init__.py"}           # tests/ excluded
    assert g.header_checked == 2 and g.header_agree == 2
    assert g.edit_hunks == 1 and g.edit_full_cov == 1


def test_strict_gold_rejects_imports_and_low_coverage():
    patch = '''--- a/pkg/core.py
+++ b/pkg/core.py
@@ -1,3 +1,3 @@
-from os import path
+from os import sep
@@ -9,4 +9,4 @@ def parse_header(value):
-    parts = value.split(";")
-    unrelated_line_one = 1
-    unrelated_line_two = 2
+    parts = value.split(",")
'''
    strict = gold.gold_for(patch, NODES, min_cov=0.5)
    lenient = gold.gold_for(patch, NODES, min_cov=0.01)
    assert strict.symbols == set() and strict.hunks_total == 2 and strict.hunks_mapped == 0   # 1/3 < 0.5; import ignored
    assert lenient.symbols == {"pkg.core.parse_header"} and lenient.edit_full_cov == 0


def test_module_candidates_and_init_ownership():
    assert gold.module_candidates("src/pkg/mod.py") == ["src.pkg.mod", "pkg.mod"]
    assert gold.module_candidates("setup.py") == ["setup"]
    fm = {m: "pkg/__init__.py" for m in gold.module_candidates("pkg/__init__.py")}
    assert gold.node_file("pkg.version", fm) == "pkg/__init__.py"
    assert gold.node_file("pkg.core.parse_header", fm) is None       # not a direct child of the package


def test_symbol_index_tiers():
    idx = signals.SymbolIndex(list(NODES))
    assert idx.resolve("pkg.core.parse_header") == [(0, "pkg.core.parse_header")]
    assert idx.resolve("core.parse_header") == [(1, "pkg.core.parse_header")]
    assert idx.resolve("PARSE_HEADER") == [(2, "pkg.core.parse_header")]
    assert (3, "pkg.core.parse_header") in idx.resolve("parse")  # substring tier only for tails >= 5 chars
    assert idx.rank(["parse_header", "helper"])[0] in {"pkg.core.parse_header", "pkg.util.helper"}


def test_bm25_vectorised_matches_reference():
    docs = [["alpha", "beta"], ["beta", "beta", "gamma"], ["delta"]]
    bm = signals.BM25(docs)
    sc = bm.scores(["beta", "gamma"])
    assert sc[1] > sc[0] > 0 and sc[2] == 0
    assert bm.rank(["beta"], ["a", "b", "c"]) == ["b", "a"]


def test_rrf_and_expand_are_deterministic():
    assert signals.rrf([["a", "b"], ["b", "c"]], k=60)[0] == "b"
    assert signals.rrf([["x"], ["y"]]) == ["x", "y"]            # tie -> id order
    adj = {"a": {"b", "c"}, "b": {"a", "d"}, "c": {"a"}, "d": {"b"}}
    assert signals.expand(["a"], adj, 1) == ["a", "b", "c"]
    assert signals.expand(["a"], adj, 2) == ["a", "b", "c", "d"]
    assert signals.hop_distance(["a"], {"d"}, adj) == 2
    assert signals.hop_distance(["a"], {"zz"}, adj) is None


def test_identifier_extraction_plus():
    issue = 'Crash:\n```\nFile "lib/pkg/core.py", line 3, in parse_header\nfrom pkg.util import helper\n```\nsee `Client.close`'
    base = signals.extract_identifiers(issue)
    plus = signals.extract_identifiers_plus(issue)
    assert "Client.close" in base
    assert plus[0] in {"parse_header", "pkg.core.parse_header"} and "pkg.util.helper" in plus


def test_metrics_first_hit_tokens_coverage():
    ranked = ["pkg.util.helper", "pkg.core.parse_header", "pkg.core.other"]
    goldset = {"pkg.core.parse_header", "pkg.core.Client.close"}
    assert metrics.first_hit(ranked, goldset) == 1
    t = metrics.tokens_to_hit(ranked, goldset, NODES)
    assert t == len(NODES["pkg.util.helper"]) // 4 + len(NODES["pkg.core.parse_header"]) // 4
    assert metrics.gold_coverage(ranked, goldset, 10) == 0.5
    oc = [metrics.outcome(ranked, goldset, NODES), metrics.outcome([], goldset, NODES)]
    assert metrics.hits_at(oc, 1).tolist() == [0.0, 0.0] and metrics.hits_at(oc, 2).tolist() == [1.0, 0.0]
    assert metrics.rr(oc).tolist() == [0.5, 0.0]


def test_bootstrap_and_paired_tests():
    v = np.array([1, 0] * 50, dtype=float)
    m, lo, hi = metrics.bootstrap_ci(v, 2000, 0)
    assert m == 0.5 and lo < 0.5 < hi and metrics.bootstrap_ci(v, 2000, 0) == (m, lo, hi)  # deterministic
    a, b = np.ones(30), np.zeros(30)
    pb = metrics.paired_bootstrap(a, b, 2000, 0)
    assert pb["diff"] == 1.0 and pb["lo"] == 1.0 and pb["p_boot"] < 0.01
    assert metrics.mcnemar_exact(np.array([1, 1, 1, 1, 1]), np.array([0, 0, 0, 0, 0]))["p"] == pytest.approx(0.0625)
    assert metrics.mcnemar_exact(np.array([1, 0]), np.array([1, 0]))["p"] == 1.0
    adj = metrics.holm({"x": 0.01, "y": 0.04, "z": 0.5})
    assert adj["x"] == pytest.approx(0.03) and adj["y"] == pytest.approx(0.08) and adj["z"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        metrics.paired_bootstrap(np.ones(2), np.ones(3))


def test_template_filling_is_strict():
    from locstudy import report
    docs = {"s": {"a": {"b": [0.5, 0.4, 0.6]}, "n": 115, "x": 0.1234}}
    out = report.fill_template("R={{s:a/b|ci}} n={{s:n|int}} x={{s:x|f3}} p={{s:a/b/0|pct}}", docs)
    assert out == "R=50.0% [40.0, 60.0] n=115 x=0.123 p=50.0%"
    with pytest.raises(KeyError):
        report.fill_template("{{s:missing/path}}", docs)
    tpl = "A<!-- if:llm --> B={{llm:x|f2}}<!-- endif -->C"
    assert report.fill_template(tpl, docs) == "AC"                                   # block dropped, slot not evaluated
    assert report.fill_template(tpl, {**docs, "llm": {"x": 1.5}}) == "A B=1.50C"
    assert report.fill_template("{{s:a~b|int}}", {"s": {"a/b": 7}}) == "7"         # "~" escapes "/" in keys
    neg = "<!-- if:!llm -->no model<!-- endif --><!-- if:llm -->model<!-- endif -->"
    assert report.fill_template(neg, docs) == "no model" and report.fill_template(neg, {**docs, "llm": {"x": 1}}) == "model"
    assert report.fill_template("p {{s:p|p}}, q {{s:q|p}}, d {{s:d|dpct}}", {"s": {"p": 0.0004, "q": 0.0574, "d": -0.0526}}) == \
        "p < 0.001, q = 0.057, d -5.3 pp"


def test_claims_guard_the_prose():
    from locstudy import report
    docs = {"s": {"p": 0.03, "d": 0.1, "k=(1, 2)": {"v": 0.2}}, "llm": {"p": 0.2}}
    ok = "Significant.<!-- claim: s:p < 0.05 --> Positive.<!-- claim: s:d > s:k=(1, 2)/v -->"
    assert report.fill_template(ok.replace("> s:k", "< s:k"), docs) == "Significant. Positive."   # stripped once true
    with pytest.raises(report.ClaimError, match="s:p >= 0.05"):
        report.fill_template("Not significant.<!-- claim: s:p >= 0.05 -->", docs)
    gated = "<!-- if:llm -->Model wins.<!-- claim: llm:p < 0.05 --><!-- endif -->"
    assert report.fill_template(gated, {"s": docs["s"]}) == ""                       # dropped block: claim not checked
    with pytest.raises(report.ClaimError):
        report.fill_template(gated, docs)
    with pytest.raises(KeyError):
        report.fill_template("x<!-- claim: s:missing < 1 -->", docs)                  # a claim on a missing value never passes


def test_llm_analysis_on_synthetic_rows(tmp_path):
    from locstudy import llm_analysis
    def oc(rank):
        return {"rank": rank, "tokens": None if rank is None else 100 * (rank + 1), "cov10": 0.0, "list_len": 50}
    rows = []
    for i in range(40):
        named = i % 2 == 0
        sym = {s: oc(None) for s in ("ident", "ident+", "emb", "graph", "graph2", "rrf")}
        sym.update(bm25=oc(30 if not named else 3), **{"rrf+": oc(1 if named else None)},
                   hyp=oc(0 if named else 8), hyp_fused=oc(0), rerank50=oc(2), policy=oc(1 if named else 2))
        rows.append({"id": f"t{i}", "repo": "r/r", "has_ident": named, "n_gold": 1, "sym": sym, "llm": {}})
    rows.append({"id": "broken", "error": "TimeoutError"})
    rp = tmp_path / "rows.jsonl"
    rp.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    res = llm_analysis.analyze(rp, tmp_path / "missing_meta.json", tmp_path / "out.json", study.Params(n_boot=200))
    assert res["failed_tasks"] == ["broken"] and res["all"]["n"] == 40 and res["no_named_symbol"]["n"] == 20
    assert res["no_named_symbol"]["rerank50"]["R@5"][0] == 1.0 and res["no_named_symbol"]["bm25"]["R@5"][0] == 0.0
    h2 = res["tests"]["H2_anchorfree_R@5"]["rerank50"]
    assert h2["diff_new_minus_bm25"] == 1.0 and h2["mcnemar_p"] < 0.001
    assert set(res["tests"]) == set(llm_analysis.HYPOTHESES)
    # ceiling: anchor-free BM25 rank 30 < 50 -> every task reachable, and the re-rank (rank 2) hits within 5
    ce = res["ceiling"]["no_named_symbol"]
    assert ce["n_reachable"] == 20 and ce["reachable"][0] == 1.0 and ce["R@5_given_reachable"][0] == 1.0
    assert ce["pools"]["bm25@100"][0] == 1.0 and res["cost"] == {"n": 0}
    ex = res["exploratory"]
    assert set(ex) == {e[0] for e in llm_analysis.EXPLORATORY}
    assert ex["rerank50_vs_rrf+_named_R@5"]["diff"] == 0.0                      # both rank within top-5 on named tasks
    assert all(ex[k]["mcnemar_p_holm"] >= ex[k]["mcnemar_p"] for k in ex)       # Holm never lowers a p-value
    from locstudy import report
    report.render_llm(res, tmp_path / "R.md")
    md = (tmp_path / "R.md").read_text(encoding="utf-8")
    assert "rerank50 − bm25 = +100.0 pp" in md and "Exploratory paired tests" in md and "Re-rank ceiling" in md


def test_task_type_heuristic():
    assert study.task_type("🐛 Fix crash in parser") == "bug"
    assert study.task_type("✨ Add support for SSE") == "feature"
    assert study.task_type("Docs tweak") == "other"


def test_end_to_end_on_synthetic_dataset(tmp_path):
    (tmp_path / "graphs").mkdir()
    (tmp_path / "embeddings").mkdir()
    task = {"instance_id": "pkg_1", "repo": "acme/pkg", "base_commit": "c0ffee", "patch": PATCH,
            "problem_statement": "🐛 parse_header keeps whitespace\nCalling `parse_header` returns padded values.",
            "hints_text": "", "created_at": "2026-01-01"}
    (tmp_path / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
    g = {"directed": True, "multigraph": True, "graph": {},
         "nodes": [{"id": k, "name": k, "text": v} for k, v in NODES.items()],
         "edges": [{"source": "pkg.util.helper", "target": "pkg.core.parse_header", "type": "calls", "key": 0}]}
    (tmp_path / "graphs" / "pkg_c0ffee.json").write_text(json.dumps(g), encoding="utf-8")
    rng = np.random.default_rng(0)
    np.savez(tmp_path / "embeddings" / "pkg_c0ffee.npz", **{k: rng.normal(size=256).astype(np.float32) for k in NODES})
    data.load_graph.cache_clear()
    out = tmp_path / "results"
    s = study.run(tmp_path, out, study.Params(n_boot=200), log=lambda *_: None)
    assert s["coverage"]["with_gold_symbol"] == 1 and s["coverage"]["label_header_agreement"][2] == 1.0
    assert s["symbol_level"]["ident"]["R@1"][0] == 1.0     # the issue names the edited function
    assert (out / "summary.json").exists() and (out / "private" / "rows.jsonl").exists()
    assert s["provenance"]["data"]["tasks.jsonl"] and s["provenance"]["params"]["rrf_k"] == 60


def test_agent_summary_and_table(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import agent_summary
    from locstudy.report import agent_table
    runs = tmp_path / "agent_runs"
    runs.mkdir()
    s = {"n": 3, "gold_solvable": 2, "resolved_on_solvable": 1, "timeouts": 1, "empty_patch": 0, "no_edit": 0,
         "tasks_with_arg_errors": 1, "first_edit_s_median": 50.0, "totals": {"calls": 9, "arg_errors": 1}}
    (runs / "S1.json").write_text(json.dumps({"summary": s, "config": {"eval_config": {"max_time_minutes": 5.0}},
                                              "per_task": {"rich_1": {}, "rich_2": {}, "httpx_3": {}}}))
    csv_ = tmp_path / "runs.csv"
    csv_.write_text("date,experiment_id,config_hash,public_score,status,notes\nd,S1,h1,0.125,COMPLETE,x\nd,S2,h2,,PENDING,y\n")
    doc = agent_summary.build(runs, csv_)
    assert doc["tags"] == ["S1", "S2"] and doc["scored"] == {"S1": 0.125} and doc["baseline"] == "S1"
    p = doc["runs"]["S1"]["panel"]
    assert p["repos"] == ["httpx", "rich"] and p["resolve_rate"] == 0.5 and p["backtick_args"] == 0 and p["max_time_minutes"] == 5.0
    tbl = agent_table(doc)
    assert "| S1 | 3 (2) | 1 | 1 | 1 | 50 | 0.125 |" in tbl and "| S2 | – | – | – | – | – | pending |" in tbl
    from locstudy.report import agent_table_compact
    tbl = agent_table_compact(doc)
    assert "| S1 | 1/2 | 1 | 1 | 0.125 |" in tbl and "| S2 | – | – | – | pending |" in tbl


def test_paper_word_limit_counts_rendered_text_only(tmp_path):
    from locstudy.report import MAX_WORDS, word_count
    assert MAX_WORDS == 3000 and word_count("one two <!-- claim: a > b -->\nthree <!-- x\ny -->") == 3


def test_agent_summary_carries_failure_aggregate(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import agent_summary
    runs = tmp_path / "agent_runs"
    runs.mkdir()
    audit = tmp_path / "failure_audit.json"
    audit.write_text(json.dumps({"by_tag": {}, "aggregate": {"right_file_share": 0.5}}))
    assert agent_summary.build(runs, tmp_path / "none.csv", audit)["failure"] == {"right_file_share": 0.5}
    assert "failure" not in agent_summary.build(runs, tmp_path / "none.csv")
