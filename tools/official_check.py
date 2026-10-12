"""Compile a bundle with the grader's own libraries (run with third_party/venv's Python 3.13).

    third_party/venv/Scripts/python tools/official_check.py build/submission [--show-prompt]

1. adk_submission.validate_directory with the competition limits (swegemma.config.build_submission_limits)
2. compile_submission with tool names bound to stand-ins and the competition model alias -> a live ADK agent tree
3. lists the tools the model will actually see (harness tools + SkillToolset tools), the generation config
   and instruction size, and renders the harness' initial user prompt (build_agent_prompt) for a sample task.
Exit code 0 only if everything compiles and the agent exposes run_skill_script, submit_patch and run_command.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from adk_submission import ModelRegistry, compile_submission, validate_directory
from google.adk.models.lite_llm import LiteLlm
from swegemma.config import build_submission_limits

MODEL = "gemma-4-31b-it-qat-w4a16-ct"
HARNESS_TOOLS = ("run_command", "submit_patch", "get_status", "read_file", "edit_file", "write_file",
                 "get_code_neighbors", "search_similar_code", "get_code_subgraph")


def _stand_ins() -> dict:
    def run_command(command: str) -> str:
        """Executes a shell command in /bin/bash -c inside /workspace."""
        return "{}"

    def submit_patch() -> str:
        """Stages untracked files and captures git diff HEAD from /workspace."""
        return "{}"

    def get_status() -> str:
        """Returns live budget consumption and patch status."""
        return "{}"

    def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """Reads a file from /workspace with 1-indexed inclusive line slicing."""
        return "{}"

    def edit_file(filepath: str, old_string: str, new_string: str, allow_multiple: bool = False) -> str:
        """Replaces old_string with new_string in an existing non-empty file inside /workspace."""
        return "{}"

    def write_file(filepath: str, content: str) -> str:
        """Creates or overwrites a file at /workspace/<filepath>."""
        return "{}"

    def get_code_neighbors(node: str, edge_type: str | None = None, max_neighbors: int = 50) -> str:
        """Graph neighbours."""
        return "{}"

    def search_similar_code(query: str, k: int = 10) -> str:
        """Embedding search."""
        return "{}"

    def get_code_subgraph(nodes: list[str]) -> str:
        """Induced subgraph."""
        return "{}"

    return {f.__name__: f for f in (run_command, submit_patch, get_status, read_file, edit_file, write_file,
                                    get_code_neighbors, search_similar_code, get_code_subgraph)}


async def _tool_names(agent) -> list[str]:
    names = []
    for t in agent.tools:
        if hasattr(t, "get_tools"):
            names += [x.name for x in await t.get_tools()]
        else:
            names.append(getattr(t, "name", None) or getattr(t, "__name__", str(t)))
    return names


def main() -> int:
    bundle = Path(sys.argv[1]).resolve()
    limits, gen = build_submission_limits()
    validate_directory(str(bundle), limits=limits)
    models = ModelRegistry()
    models.register(MODEL, LiteLlm(model=f"openai/{MODEL}", api_base="http://127.0.0.1:9/v1", api_key="EMPTY"))
    agent = compile_submission(submission_dir=bundle, tool_registry=_stand_ins(), model_registry=models,
                               limits=limits, generation_constraints=gen, script_timeout=100)
    tools = asyncio.run(_tool_names(agent))
    gc = agent.generate_content_config
    report = {"agent": agent.name, "class": type(agent).__name__, "tools": tools,
              "instruction_chars": len(agent.instruction or ""), "sub_agents": [a.name for a in agent.sub_agents],
              "generate_content_config": json.loads(gc.model_dump_json(exclude_none=True)) if gc else None}
    print(json.dumps(report, indent=1))
    missing = {"run_skill_script", "submit_patch", "run_command"} - set(tools)
    if missing:
        print(f"MISSING TOOLS: {sorted(missing)}")
        return 1
    if "--show-prompt" in sys.argv:
        from swegemma.harness.agent_runner import _extract_declared_tools, build_agent_prompt
        import yaml
        ev = (yaml.safe_load((bundle / "eval_config.yaml").read_text()) or {}).get("evaluation", {})
        cfg = SimpleNamespace(
            budget=SimpleNamespace(time_minutes=ev.get("max_time_minutes"), tool_calls=ev.get("max_tool_calls"),
                                   turns=ev.get("max_turns"), cost_usd=None),
            harness=SimpleNamespace(command_timeout_seconds=ev.get("timeout_seconds"), max_stdout_chars=5000,
                                    max_file_lines=150, max_file_chars=10000),
            graph_dir=None, embeddings_dir=None, enable_sandbox_testing=True)
        task = SimpleNamespace(repo="org/project", problem_statement="<ISSUE TEXT>", hints_text="", base_commit="abc")
        print("----- initial user prompt -----")
        print(build_agent_prompt(task, cfg, "<workspace tree>", enable_sandbox_testing=True,
                                 declared_tools=_extract_declared_tools(agent)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
