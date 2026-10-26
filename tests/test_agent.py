"""Tests for the submission bundle: skill scripts (localize, finalize) and the builder. Synthetic repos only."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "agent" / "skills" / "swe" / "scripts"
sys.path.insert(0, str(ROOT))


sys.dont_write_bytecode = True  # importing the skill scripts must not drop __pycache__ into the bundle


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


localize = _load("localize")
finalize = _load("finalize")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    files = {
        "pkg/__init__.py": "from .core import parse_header\n__all__ = ['parse_header']\n",
        "pkg/core.py": (
            "import re\n\nDEFAULT_SEP = ';'\n\n\n"
            "def parse_header(value, sep=DEFAULT_SEP):\n    \"\"\"Split a header value into parts.\"\"\"\n"
            "    parts = value.split(sep)\n    if not parts:\n        raise ValueError(\"empty header value\")\n"
            "    return parts[0]\n\n\n"
            "class Client:\n    \"\"\"HTTP client with retries.\"\"\"\n\n    timeout = 5\n\n"
            "    def close(self):\n        self.closed = True\n\n"
            "    @property\n    def is_closed(self):\n        return getattr(self, 'closed', False)\n"),
        "pkg/render.py": "def render_table(rows, width=80):\n    return '\\n'.join(str(r)[:width] for r in rows)\n",
        "pkg/broken.py": "def oops(:\n    pass\n",
        "docs/example.py": "def parse_header_example():\n    return 'parse header example'\n",
        "tests/test_core.py": "from pkg.core import parse_header\n\ndef test_parse_header():\n    assert parse_header('a;b') == 'a'\n",
        "conftest.py": "# harness hook\n",
        "pytest.ini": "[pytest]\n",
    }
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=t", "add", "-A")
    git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "baseline")
    return tmp_path


def run_localize(repo: Path, query: str, *extra: str) -> str:
    r = subprocess.run([sys.executable, str(SCRIPTS / "localize.py"), "--query", query, "--root", str(repo), *extra],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


# ---------- parity with the measured pipeline (locstudy) ----------
def test_tokenizer_identifiers_and_bm25_match_locstudy():
    from locstudy import signals
    texts = ["`Console.print` raises ValueError when soft_wrap=True in rich.console",
             "HTTPParser.complete -> reset(); Don't raise KeyboardException", "plain words only here"]
    for t in texts:
        assert localize.toks(t) == signals.toks(t)
        assert localize.extract_identifiers(t) == signals.extract_identifiers(t)
    assert localize.STOP == signals.STOP
    docs = [signals.toks(t) for t in texts + ["console print print", "reset parser"]]
    ref, ours = signals.BM25(docs), localize.BM25(docs)
    q = signals.toks("console print reset parser")
    s = ours.scores(q)
    assert np.allclose(ref.scores(q), [s.get(i, 0.0) for i in range(len(docs))], atol=1e-12)
    assert localize.rrf([["a", "b"], ["b", "c"]]) == pytest.approx({"a": 1 / 61, "b": 1 / 62 + 1 / 61, "c": 1 / 62})


# ---------- localize ----------
def test_localize_anchored_ranks_named_symbol_first(repo):
    out = run_localize(repo, "parse_header returns wrong part for 'a; b' with custom sep")
    assert out.startswith("mode: anchored") and "parse_header" in out.splitlines()[0]
    first = next(l for l in out.splitlines() if l.strip().startswith("1."))
    assert "pkg/core.py:6-11" in first and "parse_header" in first and "def parse_header(value, sep=DEFAULT_SEP):" in first
    assert "RELATED TESTS" in out and "tests/test_core.py" in out
    assert "tests/test_core.py:" not in out          # tests are never offered as edit targets
    assert "pkg/broken.py" in out or "symbols" in out  # unparsable module indexed as one symbol, no crash


def test_localize_lexical_mode_literal_and_aux_penalty(repo):
    out = run_localize(repo, 'header value is empty and the error says "empty header value"')
    assert out.startswith("mode: lexical")
    assert 'LITERAL MATCHES: "empty header value" -> pkg/core.py:10' in out
    ranks = [l for l in out.splitlines() if l[:3].strip().rstrip(".").isdigit()]
    core = next(i for i, l in enumerate(ranks) if "parse_header  def" in l)
    docs = [i for i, l in enumerate(ranks) if "docs/example.py" in l]
    assert not docs or core < docs[0]


def test_localize_methods_properties_classes_and_module_level(repo):
    # ALL_CAPS names tokenize to nothing (paper tokenizer kept: the camel/acronym-aware variant was not better on the
    # 114 dev tasks, results/container_policy.json), so the module-level symbol is reached through other words here
    out = run_localize(repo, "Client.is_closed property wrong after close; import re module", "--k", "40")
    assert "pkg/core.py:22-24  Client.is_closed" in out       # decorator line included in the range
    assert "Client.close" in out and "<module>" in out
    assert len(out) <= localize.MAX_OUT_CHARS


def test_localize_robustness(repo, tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPTS / "localize.py"), "--root", str(repo)], capture_output=True, text=True)
    assert r.returncode == 2 and "query" in r.stdout                       # missing query: guidance, not a crash
    empty = tmp_path / "empty"
    empty.mkdir()
    r = subprocess.run([sys.executable, str(SCRIPTS / "localize.py"), "--query", "x", "--root", str(empty)],
                       capture_output=True, text=True)
    assert "No Python source" in r.stdout
    lits = localize.literals("ValueError: invalid literal for int() and \"some message here\"")
    assert lits[0] == "some message here" and lits[1].startswith("invalid literal for int()") and len(lits) == 2
    out = run_localize(repo, "the and of")                                  # only stop words: guidance, no empty list
    assert out.startswith("No symbol matches the query")
    assert localize.module_name("src/pkg/sub/__init__.py") == "pkg.sub"


def test_localize_runs_through_adk_skill_wrapper(repo, tmp_path):
    """The grader runs skills via a self-extracting wrapper that chdirs into a temp dir; root must still be found."""
    pytest.importorskip("google.adk")
    from google.adk.tools.skill_toolset import _SkillScriptCodeExecutor
    from google.adk.skills._utils import _load_skill_from_dir
    skill = _load_skill_from_dir(ROOT / "agent" / "skills" / "swe")
    ex = _SkillScriptCodeExecutor(base_executor=None, script_timeout=60)
    code = ex._build_wrapper_code(skill, "scripts/localize.py", {"query": "parse_header sep"})
    w = tmp_path / "wrapper.py"
    w.write_text(code, encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"], "PYTHONPATH": str(repo), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    r = subprocess.run([sys.executable, str(w)], cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "pkg/core.py:6-11" in r.stdout, r.stdout + r.stderr


# ---------- finalize ----------
def test_finalize_cleans_and_reports(repo):
    (repo / "pkg" / "core.py").write_text((repo / "pkg" / "core.py").read_text().replace("parts[0]", "parts[0].strip()"))
    (repo / "tests" / "test_core.py").write_text("# agent edited a test\n")
    (repo / "tests" / "test_new.py").write_text("def test_x(): pass\n")
    (repo / "pytest.ini").write_text("[pytest]\naddopts = -x\n")
    (repo / "repro.py").write_text("print(1)\n")
    (repo / "pkg" / "core.py.orig").write_text("old\n")
    (repo / "pkg" / "newmod.py").write_text("def helper():\n    return 1\n")
    rc = finalize.main(["--root", str(repo)])
    assert rc == 0
    status = git(repo, "status", "--porcelain", "--untracked-files=all")
    assert "tests/" not in status and "pytest.ini" not in status and "repro.py" not in status and ".orig" not in status
    assert " M pkg/core.py" in status and "?? pkg/newmod.py" in status
    assert (repo / "tests" / "test_core.py").read_text().startswith("from pkg.core")


def test_finalize_syntax_error_and_empty_patch(repo, capsys):
    git(repo, "rm", "-q", "--cached", "pkg/broken.py")  # pretend the broken file is new, then check reporting
    (repo / "pkg" / "broken.py").unlink()
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "drop broken")
    assert finalize.main(["--root", str(repo)]) == 0
    assert "EMPTY" in capsys.readouterr().out
    (repo / "pkg" / "render.py").write_text("def render_table(rows:\n")
    assert finalize.main(["--root", str(repo), "--dry-run"]) == 1
    out = capsys.readouterr().out
    assert "SYNTAX ERRORS" in out and "pkg/render.py:1" in out and "OK: call submit_patch" not in out


# ---------- builder ----------
def test_bundle_validates_and_builds_reproducibly(tmp_path):
    from tools import build_submission as bs
    staged = bs.stage(ROOT / "agent", tmp_path / "s")
    info = bs.validate(staged)
    assert info["models"] == [bs.MODEL] and info["worst_case_hours"] <= 11.5
    z1, z2 = bs.build_zip(staged), bs.build_zip(bs.stage(ROOT / "agent", tmp_path / "s2"))
    assert z1 == z2
    names = set(zipfile.ZipFile(__import__("io").BytesIO(z1)).namelist())
    assert {"agent.yaml", "eval_config.yaml", "configs/sampling.yaml", "prompts/system.md", "skills/swe/SKILL.md",
            "skills/swe/scripts/localize.py", "skills/swe/scripts/finalize.py", "skills/swe/scripts/replace_lines.py"} == names
    nb = bs.kernel_notebook(z1, "x" * 64, "t")
    assert "/kaggle/working/submission.zip" in "".join(nb["cells"][0]["source"])


def test_bundle_rejects_bad_configs(tmp_path):
    import shutil
    from tools import build_submission as bs
    b = tmp_path / "b"
    bs.stage(ROOT / "agent", b)
    (b / "eval_config.yaml").write_text("evaluation:\n  max_time_minutes: 8\n")
    with pytest.raises(bs.BundleError, match="worst case"):
        bs.validate(b)
    bs.stage(ROOT / "agent", b)
    (b / "agent.yaml").write_text((b / "agent.yaml").read_text().replace("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-12b-it"))
    with pytest.raises(bs.BundleError, match="models must be"):
        bs.validate(b)
    bs.stage(ROOT / "agent", b)
    (b / "notes.pkl").write_bytes(b"x")
    with pytest.raises(bs.BundleError, match="disallowed extension"):
        bs.validate(b)


def test_no_backticks_reach_the_model(repo):
    """Gemma copied backticked call examples into tool arguments in the S1 dev run (48 calls, 14/24 tasks broken):
    the prompt, the skill file and every script output the model reads must be backtick-free."""
    for f in (ROOT / "agent" / "prompts" / "system.md", ROOT / "agent" / "skills" / "swe" / "SKILL.md"):
        assert "`" not in f.read_text(encoding="utf-8"), f
    out = run_localize(repo, "parse_header returns wrong part; error says \"empty header value\"")
    assert "`" not in out
    (repo / "pkg" / "render.py").write_text("def render_table(rows:\n")
    r = subprocess.run([sys.executable, str(SCRIPTS / "finalize.py"), "--root", str(repo), "--dry-run"],
                       capture_output=True, text=True)
    assert "`" not in r.stdout
    (repo / "tmp_new_lines.txt").write_text("    return parts[0]\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "replace_lines.py"), "--root", str(repo), "--file", "pkg/core.py",
                        "--start", "11", "--end", "11"], capture_output=True, text=True)
    assert r.stdout.startswith("OK") and "`" not in r.stdout


def test_localize_shows_rank1_source_only_when_anchored(repo):
    out = run_localize(repo, "parse_header returns wrong part for custom sep")
    assert "SOURCE OF #1 pkg/core.py lines 6-11" in out
    assert "def parse_header(value, sep=DEFAULT_SEP):\n" in out and "----- end -----" in out
    assert "SOURCE OF #1" not in run_localize(repo, 'header value is empty, error "empty header value"')  # lexical mode


def test_finalize_removes_workspace_tmp_dir(repo):
    (repo / "tmp").mkdir()
    (repo / "tmp" / "check.py").write_text("print(1)\n")
    assert finalize.main(["--root", str(repo)]) == 0
    assert not (repo / "tmp" / "check.py").exists()


def test_frozen_candidates_rebuild_to_their_recorded_sha(tmp_path):
    """What was evaluated on the dev panel must be what gets submitted: every frozen tag rebuilds byte-identically."""
    from tools import build_submission as bs
    for man in sorted((ROOT / "candidates").glob("*/MANIFEST.json")):
        rec = json.loads(man.read_text(encoding="utf-8"))
        staged = bs.stage(man.parent / "bundle", tmp_path / rec["tag"])
        bs.validate(staged)
        assert __import__("hashlib").sha256(bs.build_zip(staged)).hexdigest() == rec["zip_sha256"], rec["tag"]
    with pytest.raises(bs.BundleError, match="frozen"):
        bs.freeze("S1", bs.stage(ROOT / "agent", tmp_path / "cur"), {"zip_sha256": "0" * 64})


def test_sampling_keeps_thinking_on_with_bounded_budget():
    """Thinking off costs 16-28 of 129 public tasks; but under the 5-minute limit every capped thinking turn costs
    ~budget/35 s (S1-S3: turns >=1,500 tokens took 28-29% of agent time), so the budget stays at or below 2,048."""
    import yaml
    cfg = yaml.safe_load((ROOT / "agent" / "configs" / "sampling.yaml").read_text(encoding="utf-8"))
    tc = cfg["thinking_config"]
    assert tc["include_thoughts"] is True and 512 <= tc["thinking_budget"] <= 2048
    assert tc["thinking_budget"] < cfg["max_output_tokens"]


# ---------- replace_lines (edit_file fallback) ----------
def run_replace(repo: Path, content: str | None, *args: str) -> subprocess.CompletedProcess:
    if content is not None:
        (repo / "tmp_new_lines.txt").write_text(content, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPTS / "replace_lines.py"), "--root", str(repo), *args],
                          capture_output=True, text=True, timeout=60)


def test_replace_lines_replaces_inserts_and_cleans_up(repo):
    """S4: 41 edit_file calls lost old_string (7 tasks); the fallback takes one code value via write_file."""
    r = run_replace(repo, '    return parts[0].strip()\n<|"|>', "--file", "pkg/core.py", "--start", "11", "--end", "11")
    assert r.returncode == 0 and "OK: pkg/core.py lines 11-11" in r.stdout and "`" not in r.stdout, r.stdout
    text = (repo / "pkg" / "core.py").read_text(encoding="utf-8")
    assert "    return parts[0].strip()\n\n\nclass Client:" in text and '<|"|>' not in text
    assert not (repo / "tmp_new_lines.txt").exists()
    r = run_replace(repo, "    # checked\n", "--file", "/workspace/pkg/core.py", "--start", "8", "--end", "7")
    assert r.returncode == 0 and "(nothing, insertion)" in r.stdout
    lines = (repo / "pkg" / "core.py").read_text(encoding="utf-8").splitlines()
    assert lines[7] == "    # checked" and lines[8] == "    parts = value.split(sep)"
    assert git(repo, "diff", "--stat").count("|") == 1


def test_replace_lines_refuses_bad_input_without_touching_files(repo):
    before = (repo / "pkg" / "core.py").read_text(encoding="utf-8")
    r = run_replace(repo, "def parse_header(value:\n", "--file", "pkg/core.py", "--start", "6", "--end", "6")
    assert r.returncode == 1 and "NOT APPLIED" in r.stdout and (repo / "tmp_new_lines.txt").exists()
    for args in (("--file", "pkg/core.py", "--start", "x", "--end", "2"),
                 ("--file", "pkg/core.py", "--start", "40", "--end", "41"),
                 ("--file", "pkg/core.py", "--start", "5", "--end", "3"),
                 ("--file", "../outside.py", "--start", "1", "--end", "1"),
                 ("--file", "pkg/missing.py", "--start", "1", "--end", "1")):
        r = run_replace(repo, None, *args)
        assert r.returncode == 2 and r.stdout.startswith("ERROR"), (args, r.stdout)
    (repo / "tmp_new_lines.txt").unlink()
    r = run_replace(repo, None, "--file", "pkg/core.py", "--start", "1", "--end", "1")
    assert r.returncode == 2 and "write_file" in r.stdout
    assert (repo / "pkg" / "core.py").read_text(encoding="utf-8") == before
    (repo / "tmp_new_lines.txt").write_text("x\n")
    assert finalize.main(["--root", str(repo)]) == 0 and not (repo / "tmp_new_lines.txt").exists()


def test_replace_lines_runs_through_adk_skill_wrapper_with_int_args(repo, tmp_path):
    pytest.importorskip("google.adk")
    from google.adk.tools.skill_toolset import _SkillScriptCodeExecutor
    from google.adk.skills._utils import _load_skill_from_dir
    skill = _load_skill_from_dir(ROOT / "agent" / "skills" / "swe")
    ex = _SkillScriptCodeExecutor(base_executor=None, script_timeout=60)
    (repo / "tmp_new_lines.txt").write_text("    return parts[-1]\n", encoding="utf-8")
    code = ex._build_wrapper_code(skill, "scripts/replace_lines.py", {"file": "pkg/core.py", "start": 11, "end": 11})
    w = tmp_path / "wrapper.py"
    w.write_text(code, encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"], "PYTHONPATH": str(repo), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    r = subprocess.run([sys.executable, str(w)], cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK: pkg/core.py lines 11-11" in r.stdout, r.stdout + r.stderr
    assert "    return parts[-1]\n" in (repo / "pkg" / "core.py").read_text(encoding="utf-8")
