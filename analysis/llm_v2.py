# ---- kernel tail, appended after the inlined locstudy modules by kernels/build_v2.py ----
# Model-in-the-loop localization (Gemma 4 31B QAT, temperature 0, thinking off), same labels/signals as the study.
#   hyp        : model proposes up to 10 fully-qualified symbols from the issue + module list -> resolved like the harness
#   hyp_fused  : RRF of hyp, Identifiers+, BM25, embedding neighbours and 2-hop graph of hyp anchors
#   rerank50   : model re-orders BM25's top-50 (id + signature + docstring line)
#   policy     : the paper's two-mode rule — RRF+ when the issue names a resolvable symbol, else rerank50
# Outputs (/kaggle/working): llm_rows.jsonl (per-task outcomes, same schema as the study), llm_raw.jsonl (raw model
# outputs, private), llm_meta.json (model, prompt hashes, vLLM args, parse/latency/token statistics).
import concurrent.futures as _cf
import time
import hashlib as _hl
import os as _os
import subprocess as _sp
import requests as _rq

KDATA = Path("/kaggle/input/competitions/gemma-4-developer-agent")
WORKDIR = Path("/kaggle/working")
API = "http://127.0.0.1:8000/v1"
SERVED = "gemma4"
VLLM_ARGS = ["--tensor-parallel-size", "{tp}", "--max-model-len", "16384", "--gpu-memory-utilization", "0.80",
             "--max-num-seqs", "16", "--reasoning-parser", "gemma4"]
SYSTEM = "You localize bugs in Python repositories. Reply with one JSON object only."
P_HYP = ("Repository: {repo}\nModules (most common first): {modules}\n\nIssue:\n{issue}\n\n"
         "List up to 10 fully-qualified symbols (module.Class.method or module.function) in this repository that most "
         'likely must be edited to resolve the issue, best first. JSON: {{"symbols": ["..."]}}')
P_RERANK = ("Issue:\n{issue}\n\nCandidate symbols:\n{listing}\n\nReturn the 10 candidates most likely to need editing to "
            'resolve the issue, best first, by their numbers. JSON: {{"ranking": [numbers]}}')
PROMPT_SHA = _hl.sha256((SYSTEM + P_HYP + P_RERANK).encode()).hexdigest()[:16]


def chat(user: str, max_tokens: int) -> dict:
    body = {"model": SERVED, "temperature": 0.0, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    t0, err = time.perf_counter(), None
    for attempt in range(4):
        try:
            r = _rq.post(f"{API}/chat/completions", json=body, timeout=600)
            if r.status_code == 400 and "response_format" in body:
                body.pop("response_format")
                continue
            r.raise_for_status()
            d = r.json()
            u = d.get("usage") or {}
            return {"text": d["choices"][0]["message"].get("content") or "", "latency": time.perf_counter() - t0,
                    "prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
                    "error": None}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:200]}"
            time.sleep(5 * (attempt + 1))
    return {"text": "", "latency": time.perf_counter() - t0, "prompt_tokens": 0, "completion_tokens": 0, "error": err}


def parse_obj(s: str) -> dict | None:
    for cand in (s, (re.search(r"\{.*\}", s, re.S) or [None])[0] if s else None):
        if not cand:
            continue
        try:
            o = json.loads(cand)
            return o if isinstance(o, dict) else None
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def signature(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sig = lines[0][:140] if lines else ""
    doc = next((l.strip("\"' ") for l in lines[1:4] if l.startswith(('"""', "'''", '"', "'"))), "")
    return sig + (f"  # {doc[:100]}" if doc else "")


def module_list(ids: list[str], limit: int = 200) -> str:
    return ", ".join(m for m, _ in Counter(".".join(n.split(".")[:2]) for n in ids if "." in n).most_common(limit))


def one_task(t: Task, p: Params) -> tuple[dict, dict]:
    g = load_graph(str(KDATA), t.graph_key, p.bm25_k1, p.bm25_b)
    gold = gold_for(t.patch, g.nodes, p.gold_min_cov)
    lists, g, info = rankings(t, str(KDATA), p)
    issue = t.problem_statement
    h = chat(P_HYP.format(repo=t.repo, modules=module_list(g.ids), issue=issue[:6000]), 600)
    ho = parse_obj(h["text"]) or {}
    hyps = [s for s in (ho.get("symbols") or []) if isinstance(s, str)][:10]
    r_hyp = g.index.rank(hyps)
    anchors = (r_hyp or lists["ident+"] or lists["bm25"])[: p.n_anchors]
    hyp_fused = rrf([r_hyp, lists["ident+"], lists["bm25"], g.neighbors_by_embedding(anchors), expand(anchors, g.adj, 2)], k=p.rrf_k)
    cands = lists["bm25"][:50]
    listing = "\n".join(f"{i}. {c} :: {signature(g.nodes[c])}" for i, c in enumerate(cands))
    rr_ = chat(P_RERANK.format(issue=issue[:5000], listing=listing), 300) if cands else {"text": "", "latency": 0,
                                                                                         "prompt_tokens": 0, "completion_tokens": 0, "error": None}
    ro = parse_obj(rr_["text"]) or {}
    order = [cands[i] for i in (ro.get("ranking") or []) if isinstance(i, int) and 0 <= i < len(cands)]
    rerank50 = list(dict.fromkeys(order + lists["bm25"]))
    policy = lists["rrf+"] if info["anchors_from_ident"] else rerank50
    new = {"hyp": r_hyp, "hyp_fused": hyp_fused, "rerank50": rerank50, "policy": policy}
    row = {"id": t.instance_id, "repo": t.repo, "has_ident": info["anchors_from_ident"], "n_gold": len(gold.symbols),
           "sym": {k: outcome(v, gold.symbols, g.nodes) for k, v in {**lists, **new}.items()},
           "llm": {"hyp_parsed": "symbols" in ho, "hyp_n": len(hyps), "hyp_resolved": bool(r_hyp),
                   "rerank_parsed": "ranking" in ro, "rerank_valid": len(order),
                   "latency_s": round(h["latency"] + rr_["latency"], 2),
                   "prompt_tokens": h["prompt_tokens"] + rr_["prompt_tokens"],
                   "completion_tokens": h["completion_tokens"] + rr_["completion_tokens"],
                   "errors": [e for e in (h["error"], rr_["error"]) if e]}}
    raw = {"id": t.instance_id, "hyp_text": h["text"][:4000], "rerank_text": rr_["text"][:2000]}
    return row, raw


def start_vllm() -> dict:
    whl_dir = Path("/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse")
    tmp = Path("/tmp/wheelhouse"); tmp.mkdir(parents=True, exist_ok=True)
    for w in whl_dir.glob("*.whl"):
        if "cutlass" in w.name.lower():
            continue
        name = w.name.replace("cu128", "+cu128") if ("cu128" in w.name and "+" not in w.name) else w.name
        if not (tmp / name).exists():
            _os.symlink(w, tmp / name)
    _sp.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--force-reinstall",
             *sorted(str(w) for w in tmp.glob("*.whl"))], check=True)
    import torch
    n = torch.cuda.device_count()
    tp = 4 if n >= 4 else (2 if n >= 2 else 1)
    args = [a.format(tp=tp) for a in VLLM_ARGS]
    model_path = "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"
    env = dict(_os.environ, VLLM_WORKER_MULTIPROC_METHOD="spawn", VLLM_NO_USAGE_STATS="1",
               PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", VLLM_ENGINE_READY_TIMEOUT_S="1200")
    log = open(WORKDIR / "vllm.log", "w")
    proc = _sp.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", model_path,
                      "--served-model-name", SERVED, "--host", "127.0.0.1", "--port", "8000", *args],
                     stdout=log, stderr=_sp.STDOUT, env=env)
    for i in range(240):
        if proc.poll() is not None:
            break
        try:
            if _rq.get(f"{API}/models", timeout=5).ok:
                print(f"vLLM ready after {i * 5}s, gpus={n}, tp={tp}", flush=True)
                return {"gpus": n, "tp": tp, "args": args, "model_path": model_path}
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    log.flush()
    print((WORKDIR / "vllm.log").read_text(errors="replace")[-5000:], flush=True)
    raise RuntimeError("vLLM did not start")


def main_llm(workers: int = 8) -> None:
    t_start = time.perf_counter()
    meta = {"prompt_sha": PROMPT_SHA, "vllm": start_vllm(), "params": asdict(Params())}
    p = Params()
    tasks = [t for t in load_tasks(KDATA)]
    keep = []
    for t in tasks:  # only tasks with gold symbols, same rule as the study
        g = load_graph(str(KDATA), t.graph_key, p.bm25_k1, p.bm25_b)
        if gold_for(t.patch, g.nodes, p.gold_min_cov).symbols:
            keep.append(t)
    print(f"{len(keep)} tasks with gold symbols", flush=True)
    rows, raws = [], []
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one_task, t, p): t.instance_id for t in keep}
        for i, f in enumerate(_cf.as_completed(futs)):
            try:
                row, raw = f.result()
                rows.append(row); raws.append(raw)
            except Exception as e:  # noqa: BLE001 - one failing task must not kill the run
                rows.append({"id": futs[f], "error": f"{type(e).__name__}: {e}"[:300]})
            if i % 10 == 0:
                print(f"[{i}/{len(keep)}] {time.perf_counter() - t_start:.0f}s", flush=True)
    rows.sort(key=lambda r: r["id"]); raws.sort(key=lambda r: r["id"])
    ok = [r for r in rows if "sym" in r]
    meta.update(n_tasks=len(keep), n_ok=len(ok), wall_s=round(time.perf_counter() - t_start, 1),
                hyp_parse_rate=round(float(np.mean([r["llm"]["hyp_parsed"] for r in ok])), 4) if ok else None,
                rerank_parse_rate=round(float(np.mean([r["llm"]["rerank_parsed"] for r in ok])), 4) if ok else None,
                hyp_resolved_rate=round(float(np.mean([r["llm"]["hyp_resolved"] for r in ok])), 4) if ok else None,
                mean_latency_s=round(float(np.mean([r["llm"]["latency_s"] for r in ok])), 2) if ok else None,
                tokens=int(sum(r["llm"]["prompt_tokens"] + r["llm"]["completion_tokens"] for r in ok)))
    (WORKDIR / "llm_rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (WORKDIR / "llm_raw.jsonl").write_text("\n".join(json.dumps(r) for r in raws) + "\n", encoding="utf-8")
    (WORKDIR / "llm_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1), flush=True)


if __name__ == "__main__":
    main_llm()
