"""Tests for the submission bundle: skill scripts (localize, edit, finalize) and the builder. Synthetic repos only."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
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
edit = _load("edit")


@pytest.fixture(autouse=True)
def _tools_dir(tmp_path_factory, monkeypatch):
    """The editor install target, outside the test repo; never the real /tmp/swe of the machine running the tests."""
    d = tmp_path_factory.mktemp("swe_tools")
    monkeypatch.setenv("SWE_TOOLS_DIR", str(d))
    monkeypatch.setattr(localize, "TOOLS_DIR", str(d))
    monkeypatch.setattr(finalize, "TOOLS_DIR", str(d))
    return d


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
            "skills/swe/scripts/localize.py", "skills/swe/scripts/finalize.py", "skills/swe/scripts/edit.py"} == names
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
    outs = [run_edit(repo, block("    return parts[0]", "    return parts[0].strip()"), "pkg/core.py"),
            run_edit(repo, block("    return parts[0]", "x"), "pkg/core.py"),
            run_edit(repo, block("no such line", "x"), "pkg/core.py"),
            run_edit(repo, "", "pkg/core.py"), run_edit(repo, "x", "tests/test_core.py"),
            run_edit(repo, block("import re", "import re("), "pkg/core.py")]
    assert outs[0].returncode == 0 and all(o.returncode == 1 for o in outs[2:])
    for o in outs:
        assert "`" not in o.stdout, o.stdout


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


# ---------- edit.py (SEARCH/REPLACE editor called from run_command) ----------
def run_edit(repo: Path, payload: str, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(SCRIPTS / "edit.py"), "--root", str(repo), *args],
                       input=payload.encode("utf-8"), capture_output=True, timeout=60)
    return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8", "replace"),
                                       r.stderr.decode("utf-8", "replace"))


def block(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


def core(repo: Path) -> str:
    return (repo / "pkg" / "core.py").read_text(encoding="utf-8")


def test_edit_applies_blocks_in_order_and_reports_region(repo):
    """S4: 41 of 78 edit_file calls lost old_string (two-string calls); run_command carried 0 malformed in 807."""
    r = run_edit(repo, block('    parts = value.split(sep)\n    if not parts:', '    parts = [p.strip() for p in value.split(sep)]\n'
                             '    if not parts:') + "\n" + block("    return parts[0]", "    return parts[0] or None")
                 + "EOF`\n", "pkg/core.py")
    assert r.returncode == 0 and r.stdout.startswith("APPLIED to pkg/core.py: block 1: replaced lines 8-9"), r.stdout
    assert "block 2: replaced lines 11-11 (1) by 1 lines" in r.stdout and "    11  " in r.stdout
    text = core(repo)
    assert "    parts = [p.strip() for p in value.split(sep)]\n    if not parts:\n" in text
    assert "    return parts[0] or None\n" in text and "EOF" not in text
    assert git(repo, "diff", "--stat").count("|") == 1


def test_edit_is_all_or_nothing_and_shows_closest_lines(repo):
    before = core(repo)
    r = run_edit(repo, block("    return parts[0]", "    return parts[1]") + block("    parts = value.split(sepp)", "x"),
                 "pkg/core.py")
    assert r.returncode == 1 and "EDIT NOT APPLIED: block 2: SEARCH not found in pkg/core.py" in r.stdout
    assert "Closest region" in r.stdout and "     8      parts = value.split(sep)" in r.stdout
    assert core(repo) == before
    r = run_edit(repo, block("        self.closed = True", "x").replace("self.closed = True", "return"), "pkg/core.py")
    assert r.returncode == 1 and core(repo) == before


def test_edit_matching_tiers(repo):
    # trailing whitespace and blank edges
    r = run_edit(repo, block("\n    timeout = 5   \n", "\n    timeout = 10\n"), "pkg/core.py")
    assert r.returncode == 0 and "[matched ignoring whitespace]" in r.stdout, r.stdout
    assert "    timeout = 10\n\n    def close" in core(repo)
    # uniform indentation offset: the replacement is shifted by the same amount
    r = run_edit(repo, block("def close(self):\n    self.closed = True", "def close(self):\n    self.closed = 1"),
                 "pkg/core.py")
    assert r.returncode == 0 and "[matched ignoring indentation]" in r.stdout, r.stdout
    assert "    def close(self):\n        self.closed = 1\n" in core(repo)
    # lines copied with the numbers the editor prints
    r = run_edit(repo, block("    23      def is_closed(self):\n    24          return getattr(self, 'closed', False)",
                             "    23      def is_closed(self):\n    24          return bool(getattr(self, 'closed', False))"),
                 "pkg/core.py")
    assert r.returncode == 0 and "line numbers" in r.stdout, r.stdout
    assert "        return bool(getattr(self, 'closed', False))\n" in core(repo)
    compile(core(repo), "core.py", "exec")


def test_edit_refuses_ambiguous_empty_and_breaking_edits(repo):
    (repo / "pkg" / "dup.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 1\n", encoding="utf-8")
    before = (repo / "pkg" / "dup.py").read_text(encoding="utf-8")
    r = run_edit(repo, block("    return 1", "    return 2"), "pkg/dup.py")
    assert r.returncode == 1 and "occurs 2 times" in r.stdout and "lines 2, 6" in r.stdout
    r = run_edit(repo, block("", "    return 2"), "pkg/dup.py")
    assert r.returncode == 1 and "SEARCH is empty" in r.stdout
    r = run_edit(repo, block("def b():\n    return 1", "def b(:\n    return 1"), "pkg/dup.py")
    assert r.returncode == 1 and "would not compile" in r.stdout and "invalid syntax" in r.stdout.lower()
    assert (repo / "pkg" / "dup.py").read_text(encoding="utf-8") == before
    r = run_edit(repo, "no markers here", "pkg/dup.py")
    assert r.returncode == 1 and "no SEARCH/REPLACE block" in r.stdout
    r = run_edit(repo, "", "pkg/dup.py")
    assert r.returncode == 1 and "no edit text on stdin" in r.stdout
    # a file that did not compile before may still be edited (warned, not blocked)
    r = run_edit(repo, block("    pass", "    return 0"), "pkg/broken.py")
    assert r.returncode == 0 and "did not compile before" in r.stdout


def test_edit_is_idempotent(repo):
    b = block("    return parts[0]", "    return parts[-1]")
    assert run_edit(repo, b, "pkg/core.py").returncode == 0
    after = core(repo)
    r = run_edit(repo, b, "pkg/core.py")
    assert r.returncode == 0 and "already applied" in r.stdout and r.stdout.startswith("NO CHANGE")
    assert core(repo) == after and git(repo, "status", "--porcelain").split() == ["M", "pkg/core.py"]


def test_edit_never_claims_an_edit_it_did_not_make(repo):
    """Linux check v1: a mistyped SEARCH whose replacement text happens to exist elsewhere was reported as already
    applied. Only a block this editor applied itself may be reported so."""
    (repo / "pkg" / "two.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n", encoding="utf-8")
    r = run_edit(repo, block("    return 22", "    return 1"), "pkg/two.py")
    assert r.returncode == 1 and "SEARCH not found" in r.stdout and "already" not in r.stdout, r.stdout


def test_edit_line_ranges(repo):
    r = run_edit(repo, "    return parts[0].upper()\nEOF'\n", "pkg/core.py", "11-11")
    assert r.returncode == 0 and "REMOVED (old lines 11-11)" in r.stdout, r.stdout
    assert "    return parts[0].upper()\n\n\nclass Client:" in core(repo) and "EOF" not in core(repo)
    r = run_edit(repo, "    # checked\n", "/workspace/pkg/core.py", "8-7")
    assert r.returncode == 0 and "(nothing, insertion)" in r.stdout
    lines = core(repo).splitlines()
    assert lines[7] == "    # checked" and lines[8] == "    parts = value.split(sep)"
    for rng in ("40-41", "5-3", "x-2"):
        assert run_edit(repo, "x\n", "pkg/core.py", rng).returncode == 1, rng


def test_edit_new_files_paths_and_protection(repo):
    r = run_edit(repo, "def helper():\n    return 42\n", "pkg/sub/helpers.py")
    assert r.returncode == 0 and r.stdout.startswith("CREATED pkg/sub/helpers.py (2 lines)")
    assert (repo / "pkg" / "sub" / "helpers.py").read_text(encoding="utf-8") == "def helper():\n    return 42\n"
    r = run_edit(repo, block("", "VALUE = 1"), "pkg/const.py")
    assert r.returncode == 0 and (repo / "pkg" / "const.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    for path in ("tests/test_core.py", "pyproject.toml", "pkg/conftest.py", "../outside.py"):
        r = run_edit(repo, block("a", "b"), path)
        assert r.returncode == 1 and r.stdout.startswith("EDIT NOT APPLIED"), (path, r.stdout)
    r = run_edit(repo, block("import re", "import os"), "pkg/missing.py")
    assert r.returncode == 1 and "does not exist" in r.stdout and not (repo / "pkg" / "missing.py").exists()
    r = run_edit(repo, "def f(:\n", "pkg/bad_new.py")
    assert r.returncode == 1 and not (repo / "pkg" / "bad_new.py").exists()
    assert not list(repo.rglob(".swe_edit_*"))


def test_edit_keeps_line_endings_final_newline_and_untouched_bytes(repo):
    crlf = repo / "pkg" / "win.py"
    crlf.write_bytes(b"def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2")
    assert run_edit(repo, block("    return 1", "    x = 1\n    return x"), "pkg/win.py").returncode == 0
    assert crlf.read_bytes() == b"def a():\r\n    x = 1\r\n    return x\r\n\r\ndef b():\r\n    return 2"
    mixed = repo / "pkg" / "mixed.py"
    mixed.write_bytes(b"A = 1\r\nB = 2\nC = 3\n")
    r = run_edit(repo, block("B = 2", "B = 20"), "pkg/mixed.py")
    assert r.returncode == 0 and mixed.read_bytes() == b"A = 1\r\nB = 20\nC = 3\n", (r.stdout, mixed.read_bytes())
    uni = repo / "pkg" / "uni.py"
    uni.write_bytes("S = '\u00e9\u2603'\nT = 1\n".encode("utf-8"))
    assert run_edit(repo, block("T = 1", "T = '\u00fc'"), "pkg/uni.py").returncode == 0
    assert uni.read_bytes() == "S = '\u00e9\u2603'\nT = '\u00fc'\n".encode("utf-8")
    if os.name == "posix":
        os.chmod(mixed, 0o755)
        assert run_edit(repo, block("C = 3", "C = 30"), "pkg/mixed.py").returncode == 0
        assert os.stat(mixed).st_mode & 0o777 == 0o755


def test_edit_divider_lines_inside_code(repo):
    """A line of = signs in old or new code (RST underlines in docstrings) must not split the block wrongly."""
    doc = repo / "pkg" / "doc.py"
    doc.write_text('def f():\n    """Title\n    =======\n\n    Body.\n    """\n    return 1\n', encoding="utf-8")
    r = run_edit(repo, block('    """Title\n    =======\n\n    Body.', '    """Title\n    =======\n\n    Better body.'),
                 "pkg/doc.py")
    assert r.returncode == 0, r.stdout
    assert doc.read_text(encoding="utf-8") == 'def f():\n    """Title\n    =======\n\n    Better body.\n    """\n    return 1\n'
    r = run_edit(repo, block("    return 1", '    """\n    Usage\n    =======\n    """\n    return 1'), "pkg/doc.py")
    assert r.returncode == 0 and '    Usage\n    =======\n    """\n    return 1\n' in doc.read_text(encoding="utf-8")


def test_edit_recovers_unquoted_heredoc_from_the_shell_command_line():
    """With <<EOF bash expands $, backticks and backslashes before the editor sees stdin; the raw text is taken
    from the shell's argv instead (here a synthetic argv; /proc is read on Linux)."""
    script = (b"cd /workspace && python3 /tmp/swe/edit.py rich/markup.py <<EOF\n<<<<<<< SEARCH\n"
              b"    return markup\n=======\n    return markup.rstrip(\"\\\\\") + $X\n>>>>>>> REPLACE\nEOF\n")
    body = edit.unquoted_heredoc_body([b"/bin/bash", b"-c", script])
    assert body == '<<<<<<< SEARCH\n    return markup\n=======\n    return markup.rstrip("\\\\") + $X\n>>>>>>> REPLACE\n'
    assert edit.unquoted_heredoc_body([b"bash", b"-c", script.replace(b"<<EOF", b"<<'EOF'")]) is None
    assert edit.unquoted_heredoc_body([b"bash", b"-c", script + script]) is None  # two edits in one command
    tabbed = b"python3 /tmp/swe/edit.py a.py 3-3 <<-END\n\t\tx = 1\n\tEND\n"
    assert edit.unquoted_heredoc_body([tabbed]) == "x = 1\n"
    assert edit.unquoted_heredoc_body([b"ls -la"]) is None


def _posix_bash() -> str | None:
    """A working bash (Git for Windows' on Windows; System32's bash.exe is WSL and may be disabled)."""
    git_exe = shutil.which("git")
    cands = ["/bin/bash"] if os.name == "posix" else [
        str(Path(git_exe).resolve().parents[1] / "bin" / "bash.exe") if git_exe else "",
        r"C:\Program Files\Git\bin\bash.exe"]
    for c in cands:
        try:
            if c and subprocess.run([c, "-c", "echo ok"], capture_output=True, timeout=20).stdout.strip() == b"ok":
                return c
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


@pytest.mark.skipif(_posix_bash() is None, reason="needs bash")
def test_edit_through_a_real_bash_quoted_heredoc(repo):
    """The exact command shape the prompt teaches, run by bash; backslashes, quotes, $ and backticks pass verbatim."""
    exe = sys.executable.replace("\\", "/")
    cmd = (f"cd '{repo.as_posix()}' && '{exe}' '{(SCRIPTS / 'edit.py').as_posix()}' pkg/core.py <<'EOF'\n"
           "<<<<<<< SEARCH\n    return parts[0]\n=======\n"
           "    return parts[0].replace(\"\\\\\", \"$HOME\" + '`x`')\n>>>>>>> REPLACE\nEOF\n")
    r = subprocess.run([_posix_bash(), "-c", cmd], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "    return parts[0].replace(\"\\\\\", \"$HOME\" + '`x`')\n" in core(repo)


def test_localize_and_finalize_install_the_editor(repo, tmp_path_factory, _tools_dir, monkeypatch):
    out = run_localize(repo, "parse_header sep")
    assert out.splitlines()[-1].startswith("EDITOR READY: python3 ") and out.rstrip().endswith("edit.py"), out
    assert (_tools_dir / "edit.py").read_bytes() == (SCRIPTS / "edit.py").read_bytes()
    (_tools_dir / "edit.py").unlink()
    finalize.main(["--root", str(repo)])  # empty patch: finalize reinstalls it for the edit still to come
    assert (_tools_dir / "edit.py").exists()
    blocker = tmp_path_factory.mktemp("ro") / "file_not_dir"  # unusable tools dir: falls back to .git/swe
    blocker.write_text("x")
    monkeypatch.setattr(localize, "TOOLS_DIR", str(blocker / "sub"))
    assert "use this path instead" in localize.install_editor(str(repo))
    assert (repo / ".git" / "swe" / "edit.py").exists() and git(repo, "status", "--porcelain") == ""


def test_editor_install_runs_through_adk_skill_wrapper(repo, tmp_path, _tools_dir):
    """run_skill_script materializes every skill script in a temp dir that is deleted after the call: the editor
    must be copied out of it, then work from run_command."""
    pytest.importorskip("google.adk")
    from google.adk.tools.skill_toolset import _SkillScriptCodeExecutor
    from google.adk.skills._utils import _load_skill_from_dir
    skill = _load_skill_from_dir(ROOT / "agent" / "skills" / "swe")
    ex = _SkillScriptCodeExecutor(base_executor=None, script_timeout=60)
    w = tmp_path / "wrapper.py"
    w.write_text(ex._build_wrapper_code(skill, "scripts/localize.py", {"query": "parse_header"}), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(repo), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "SWE_TOOLS_DIR": str(_tools_dir)}
    r = subprocess.run([sys.executable, str(w)], cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "EDITOR READY" in r.stdout, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(_tools_dir / "edit.py"), "pkg/core.py"], cwd=repo, capture_output=True,
                       input=block("    return parts[0]", "    return parts[1]").encode(), timeout=60)
    assert r.returncode == 0 and "    return parts[1]\n" in core(repo), r.stdout


def test_trace_metrics_count_editor_edits():
    """From S6 edits arrive as run_command calls of the editor: they must count as edits (first edit time, no_edit,
    failure categories), with refusals and unquoted heredocs tracked."""
    from analysis import agent_traces, failure_audit

    def call(t, name, args, obs):
        return {"source": "agent", "extra": {"elapsed_s": t}, "metrics": {"completion_tokens": 10},
                "tool_calls": [{"function_name": name, "arguments": args, "extra": {"elapsed_s": t}}],
                "observation": {"content": json.dumps(obs)}}
    ed = "python3 /tmp/swe/edit.py pkg/core.py <<'EOF'\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\nEOF"
    trace = {"steps": [
        call(5.0, "run_command", {"command": "grep -rn x ."}, {"status": "ok", "stdout": ""}),
        call(9.5, "run_command", {"command": ed.replace("'EOF'", "EOF")},
             {"status": "error", "error_message": "EDIT NOT APPLIED: block 1: SEARCH not found"}),
        call(14.0, "run_command", {"command": ed}, {"status": "ok", "stdout": "APPLIED to pkg/core.py: block 1"}),
        call(20.0, "submit_patch", {}, {"status": "ok"})]}
    m = agent_traces.task_metrics(trace)
    assert m["first_edit_s"] == 9.5 and m["editor_calls"] == 2 and m["editor_not_applied"] == 1
    assert m["editor_unquoted"] == 1
    f = failure_audit.trace_facts(trace, {"pkg/core.py"})
    assert f["wrote_gold"] and f["edit_attempts"] == 2 and f["malformed_edits"] == 1
    f = failure_audit.trace_facts({"steps": trace["steps"][:2]}, {"pkg/core.py"})
    assert not f["wrote_source"] and f["edit_attempts"] == 1


def test_editor_copies_are_in_sync():
    """PROTECTED must match finalize.py; install_editor must be the same code in localize.py and finalize.py."""
    import inspect
    assert edit.PROTECTED.pattern == finalize.PROTECTED.pattern
    assert inspect.getsource(localize.install_editor) == inspect.getsource(finalize.install_editor)
