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
