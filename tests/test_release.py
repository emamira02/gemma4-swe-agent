"""Release gate and submit queue: the rules that decide what may be sent to Kaggle."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import release_gate as rg  # noqa: E402


def panel(root: Path, tag: str, rows: list[dict], traces: dict[str, list] | None = None) -> None:
    d = root / "results" / f"kaggle_eval_{tag}" / "agent_eval"
    (d / "results" / "traces").mkdir(parents=True)
    (d / "per_task.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for name, steps in (traces or {}).items():
        (d / "results" / "traces" / f"trace_{name}.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")


def row(i: int, resolved: bool, dur: float = 250.0, gold: bool = True) -> dict:
    return {"id": f"t{i}", "agent": {"resolved": resolved, "duration_s": dur}, "gold": {"resolved": gold}}


def call(name: str, args: dict, obs: str = "ok") -> dict:
    return {"tool_calls": [{"function_name": name, "arguments": args}], "observation": {"content": obs}}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg.bs, "CANDIDATES", tmp_path / "candidates")
    return tmp_path


def test_panel_sanity_rules(root):
    assert rg.panel_sanity("NONE") == {"tag": "NONE", "panel": False, "passed": False, "why": "no dev panel"}
    panel(root, "OK", [row(i, i < 5) for i in range(24)])
    assert rg.panel_sanity("OK")["passed"] and rg.panel_sanity("OK")["hours_120"] == pytest.approx(8.33, abs=0.01)
    panel(root, "SLOW", [row(i, i < 5, dur=340) for i in range(24)])  # 120 x 340 s = 11.3 h > 11 h
    assert not rg.panel_sanity("SLOW")["passed"]
    panel(root, "SHORT", [row(i, True) for i in range(14)])  # a targeted 14-task panel never qualifies
    assert not rg.panel_sanity("SHORT")["passed"]
    panel(root, "UNSOLV", [row(i, i < 5, gold=i >= 2) for i in range(24)])  # resolves on gold-failing tasks don't count
    assert rg.panel_sanity("UNSOLV")["resolved_on_solvable"] == 3 and not rg.panel_sanity("UNSOLV")["passed"]
    missing = "python3: can't open file '/w/.git/swe/edit.py': [Errno 2] No such file or directory"
    edit = {"command": "python3 /workspace/.git/swe/edit.py a.py <<'EOF'\nx\nEOF"}
    loc = {"skill_name": "swe", "file_path": "scripts/localize.py", "args": {"query": "q"}}
    panel(root, "BEFORE", [row(i, i < 5) for i in range(24)], {"t0": [call("run_command", edit, missing)]})
    assert rg.panel_sanity("BEFORE")["passed"]  # model ordering (editor before localize) is not infrastructure
    panel(root, "AFTER", [row(i, i < 5) for i in range(24)],
          {"t0": [call("run_skill_script", loc), call("run_command", edit, missing)]})
    s = rg.panel_sanity("AFTER")
    assert not s["passed"] and s["editor_missing_after_localize"] == ["t0"]


def test_submittable_needs_own_panel_or_matching_gate(root):
    (root / "candidates" / "X").mkdir(parents=True)
    ok, why = rg.submittable("X", "abc")
    assert not ok and "no GATE.json" in why
    gate = root / "candidates" / "X" / "GATE.json"
    gate.write_text(json.dumps({"passed": True, "zip_sha256": "abc", "base": "B"}), encoding="utf-8")
    assert rg.submittable("X", "abc")[0]
    assert not rg.submittable("X", "other-sha")[0]  # a gate for different bytes proves nothing
    gate.write_text(json.dumps({"passed": False, "zip_sha256": "abc"}), encoding="utf-8")
    assert not rg.submittable("X", "abc")[0]
    panel(root, "P", [row(i, False) for i in range(24)])  # own panel decides, even with a GATE.json present
    (root / "candidates" / "P").mkdir()
    (root / "candidates" / "P" / "GATE.json").write_text(json.dumps({"passed": True, "zip_sha256": "s"}), encoding="utf-8")
    assert not rg.submittable("P", "s")[0]


def test_submit_queue_file_is_well_formed():
    q = json.loads((ROOT / "submit_queue.json").read_text(encoding="utf-8"))
    tags = [e["tag"] for e in q]
    assert len(tags) == len(set(tags)) and all(e.get("hypothesis") and e.get("added") for e in q)
    for t in tags:  # every queued tag is a frozen candidate (never a baseline such as B1)
        assert (ROOT / "candidates" / t / "MANIFEST.json").exists(), t
