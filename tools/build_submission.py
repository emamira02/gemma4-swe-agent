"""Validate agent/ and build a byte-reproducible submission.zip plus the Kaggle notebook that emits it.

    python tools/build_submission.py [--agent agent] [--out build] [--kernel kernels/submit] [--tag S1]

Checks (each one a hard failure): exactly one root config; only allowed extensions; no symlinks, caches or
traversal; total size < 3 GiB; every !include / config_path resolves inside the bundle; exactly one model and it
is the competition model; sampling keys allowed and within bounds; eval_config budget fits 12 h for 120 tasks;
every skill has SKILL.md whose frontmatter name equals its directory; every .py compiles. If the official
harness is importable (third_party/venv), the bundle is also compiled with adk_submission exactly as the
grader does. Output: build/submission.zip (fixed timestamps -> same bytes for same inputs), build/MANIFEST.json,
and kernels/submit/{submit.ipynb,kernel-metadata.json}, a CPU-only notebook that writes the identical zip.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "gemma-4-31b-it-qat-w4a16-ct"
ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
ROOT_CONFIGS = ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")
MAX_BYTES = 3 * 1024 ** 3
SAMPLING_KEYS = {"temperature", "top_p", "top_k", "max_output_tokens", "presence_penalty", "frequency_penalty",
                 "stop_sequences", "response_mime_type", "seed", "thinking_config"}
EVAL_KEYS = {"timeout_seconds", "max_tool_calls", "max_time_minutes", "max_turns"}
ZIP_TIME = (2026, 1, 1, 0, 0, 0)
TEXT_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json"}
HIDDEN_TASKS, SETUP_MIN_PER_TASK, FIXED_SETUP_MIN, LIMIT_H = 120, 0.5, 15, 12.0


class BundleError(ValueError):
    pass


def _yaml():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!include", lambda loader, node: {"__include__": loader.construct_scalar(node)})
    return yaml, Loader


def _resolve_includes(obj, base: Path, bundle: Path, depth: int = 0):
    yaml, Loader = _yaml()
    if depth > 10:
        raise BundleError("!include depth > 10")
    if isinstance(obj, dict) and set(obj) == {"__include__"}:
        target = (base / obj["__include__"]).resolve()
        if bundle not in target.parents or not target.is_file():
            raise BundleError(f"!include {obj['__include__']} from {base} does not resolve inside the bundle")
        if target.suffix in (".yaml", ".yml"):
            return _resolve_includes(yaml.load(target.read_text(encoding="utf-8"), Loader=Loader), target.parent, bundle, depth + 1)
        return target.read_text(encoding="utf-8")
    if isinstance(obj, dict):
        return {k: _resolve_includes(v, base, bundle, depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_includes(v, base, bundle, depth) for v in obj]
    return obj


def _agents(cfg: dict, base: Path, bundle: Path):
    """Yield every agent config reachable from cfg (sub_agents and agent_tool)."""
    yaml, Loader = _yaml()
    yield cfg
    refs = [s.get("config_path") for s in cfg.get("sub_agents") or [] if isinstance(s, dict)]
    refs += [t["agent_tool"].get("config_path") for t in cfg.get("tools") or [] if isinstance(t, dict) and "agent_tool" in t]
    for ref in filter(None, refs):
        p = (base / ref).resolve()
        if bundle not in p.parents or not p.is_file():
            raise BundleError(f"config_path {ref} does not resolve inside the bundle")
        sub = _resolve_includes(yaml.load(p.read_text(encoding="utf-8"), Loader=Loader), p.parent, bundle)
        yield from _agents(sub, p.parent, bundle)


def validate(bundle: Path) -> dict:
    yaml, Loader = _yaml()
    bundle = bundle.resolve()
    files = sorted(p for p in bundle.rglob("*") if p.is_file() or p.is_symlink())
    problems = []
    roots = [n for n in ROOT_CONFIGS if (bundle / n).exists()]
    if len(roots) != 1:
        problems.append(f"need exactly one root config, found {roots}")
    for p in files:
        rel = p.relative_to(bundle).as_posix()
        if p.is_symlink():
            problems.append(f"symlink not allowed: {rel}")
        if p.suffix.lower() not in ALLOWED_EXT:
            problems.append(f"disallowed extension: {rel}")
        if "__pycache__" in rel or rel.endswith(".pyc") or "/." in "/" + rel:
            problems.append(f"cache/hidden file: {rel}")
        if p.suffix == ".py":
            try:
                compile(p.read_bytes(), rel, "exec", dont_inherit=True)
            except SyntaxError as e:
                problems.append(f"{rel}:{e.lineno}: {e.msg}")
    total = sum(p.stat().st_size for p in files)
    if total >= MAX_BYTES:
        problems.append(f"bundle {total} bytes >= 3 GiB")
    if problems:
        raise BundleError("; ".join(problems))
    root_cfg = _resolve_includes(yaml.load((bundle / roots[0]).read_text(encoding="utf-8"), Loader=Loader), bundle, bundle)
    agents = list(_agents(root_cfg, bundle, bundle))
    models = {re.sub(r"^(openai|google|hosted_vllm|custom)/", "", a["model"]) for a in agents if a.get("model")}
    if models != {MODEL}:
        problems.append(f"models must be exactly {{{MODEL}}}, got {sorted(models)}")
    for a in agents:
        gc = a.get("generate_content_config") or {}
        if set(gc) - SAMPLING_KEYS:
            problems.append(f"agent {a.get('name')}: disallowed generate_content_config keys {sorted(set(gc) - SAMPLING_KEYS)}")
        if not 1 <= int(gc.get("max_output_tokens", 16384)) <= 32768:
            problems.append("max_output_tokens out of [1, 32768]")
        tc = gc.get("thinking_config") or {}
        if "thinking_level" in tc:
            problems.append("thinking_level maps to reasoning_effort on vLLM; use thinking_budget + include_thoughts")
        if not 0 <= int(tc.get("thinking_budget", 4096)) <= 32768:
            problems.append("thinking_budget out of [0, 32768]")
        if not isinstance(a.get("instruction"), str) or not a["instruction"].strip():
            problems.append(f"agent {a.get('name')}: empty instruction")
        for sk in a.get("skills") or []:
            d = (bundle / sk).resolve()
            md = d / "SKILL.md"
            if bundle not in d.parents or not md.is_file():
                problems.append(f"skill {sk}: SKILL.md missing")
                continue
            text = md.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            fm = yaml.safe_load(m.group(1)) if m else None
            if not isinstance(fm, dict) or fm.get("name") != d.name or not fm.get("description"):
                problems.append(f"skill {sk}: frontmatter needs name == '{d.name}' and a description")
    ev = {}
    if (bundle / "eval_config.yaml").exists():
        raw = yaml.safe_load((bundle / "eval_config.yaml").read_text(encoding="utf-8")) or {}
        ev = raw.get("evaluation", raw)
        if set(ev) - EVAL_KEYS:
            problems.append(f"eval_config: unknown keys {sorted(set(ev) - EVAL_KEYS)}")
        cap = float(ev.get("max_time_minutes", 60))
        worst_h = (HIDDEN_TASKS * (cap + SETUP_MIN_PER_TASK) + FIXED_SETUP_MIN) / 60
        if worst_h > LIMIT_H - 0.5:
            problems.append(f"worst case {worst_h:.2f} h for {HIDDEN_TASKS} tasks leaves < 30 min of the 12 h limit")
    else:
        problems.append("eval_config.yaml missing: the 60-minute default per task cannot fit 12 h")
    if problems:
        raise BundleError("; ".join(problems))
    return {"files": len(files), "bytes": total, "agents": [a.get("name") for a in agents], "models": sorted(models),
            "eval": ev, "worst_case_hours": round((HIDDEN_TASKS * (float(ev.get("max_time_minutes", 60)) + SETUP_MIN_PER_TASK)
                                                   + FIXED_SETUP_MIN) / 60, 2)}


def official_check(bundle: Path) -> str:
    """Compile with the grader's own libraries when available (third_party/venv, Python 3.13)."""
    import subprocess
    py = ROOT / "third_party" / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not py.exists():
        return "skipped (third_party/venv not installed)"
    r = subprocess.run([str(py), str(ROOT / "tools" / "official_check.py"), str(bundle)], capture_output=True,
                       text=True, timeout=600)
    if r.returncode != 0:
        raise BundleError("official compile failed: " + (r.stdout + r.stderr).strip()[-1500:])
    report = json.loads(r.stdout[r.stdout.index("{"):r.stdout.rindex("}") + 1])
    return f"compiled: {report['class']} with tools {report['tools']}"


def stage(src: Path, dst: Path) -> Path:
    """Copy the bundle without interpreter caches or hidden files (they are never part of a submission)."""
    import shutil
    if dst.exists():
        shutil.rmtree(dst)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_dir() or "__pycache__" in rel.parts or p.suffix == ".pyc" or any(x.startswith(".") for x in rel.parts):
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst / rel) if not p.is_symlink() else (dst / rel).symlink_to(p.readlink())
    return dst


def build_zip(bundle: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():
                info = zipfile.ZipInfo(p.relative_to(bundle).as_posix(), date_time=ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                data = p.read_bytes()
                if p.suffix.lower() in TEXT_EXT:  # LF everywhere: same bytes from a Windows or Linux checkout
                    data = data.replace(b"\r\n", b"\n")
                z.writestr(info, data)
    return buf.getvalue()


def kernel_notebook(zip_bytes: bytes, sha: str, tag: str) -> dict:
    b64 = base64.b64encode(zip_bytes).decode()
    src = f'''# Writes the agent bundle {tag} (sha256 {sha}) to /kaggle/working/submission.zip. CPU only, no inputs needed.
import base64, hashlib, zipfile
from pathlib import Path
ZIP_B64 = "{b64}"
data = base64.b64decode(ZIP_B64)
assert hashlib.sha256(data).hexdigest() == "{sha}", "bundle corrupted"
out = Path("/kaggle/working/submission.zip")
out.write_bytes(data)
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    names = z.namelist()
    assert "agent.yaml" in names
print("wrote", out, len(data), "bytes;", names)
'''
    return {"cells": [{"cell_type": "code", "execution_count": None, "id": "submit", "metadata": {}, "outputs": [],
                       "source": src.splitlines(keepends=True)}],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", type=Path, default=ROOT / "agent")
    ap.add_argument("--out", type=Path, default=ROOT / "build")
    ap.add_argument("--kernel", type=Path, default=ROOT / "kernels" / "submit")
    ap.add_argument("--kernel-id", default="emanuelemiranda/g4-agent-submit")
    ap.add_argument("--tag", default="dev")
    a = ap.parse_args(argv)
    staged = stage(a.agent, a.out / "submission")
    info = validate(staged)
    info["official"] = official_check(staged)
    data = build_zip(staged)
    sha = hashlib.sha256(data).hexdigest()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "submission.zip").write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info["zip_files"] = {n: hashlib.sha256(z.read(n)).hexdigest()[:12] for n in z.namelist()}
    info.update(tag=a.tag, zip_sha256=sha, zip_bytes=len(data))
    (a.out / "MANIFEST.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    a.kernel.mkdir(parents=True, exist_ok=True)
    (a.kernel / "submit.ipynb").write_text(json.dumps(kernel_notebook(data, sha, a.tag), indent=1), encoding="utf-8")
    meta = {"id": a.kernel_id, "title": "g4-agent-submit", "code_file": "submit.ipynb", "language": "python",
            "kernel_type": "notebook", "is_private": True, "enable_gpu": False, "enable_tpu": False,
            "enable_internet": False, "dataset_sources": [], "competition_sources": ["gemma-4-developer-agent"],
            "kernel_sources": [], "model_sources": []}
    (a.kernel / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("tag", "zip_sha256", "zip_bytes", "files", "worst_case_hours", "official")}, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BundleError as e:
        print(f"BUNDLE INVALID: {e}", file=sys.stderr)
        sys.exit(1)
