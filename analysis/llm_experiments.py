# ---- appended after analysis/localization.py by kernels/build.py (relies on its definitions) ----
# Model-in-the-loop localization experiments on the 129 dev tasks, run inside a private Kaggle notebook:
#   A) anchor hypothesis: Gemma 4 proposes fully-qualified symbols from the issue + module list; resolve them like the harness
#   B) re-ranking: Gemma 4 re-orders the BM25 top-50 candidates (id + signature + docstring line)
# All numbers are written to /kaggle/working/llm_localization_results.json.
import concurrent.futures as _cf
import os as _os
import subprocess as _sp

import requests as _rq

KAGGLE = Path("/kaggle/input/competitions/gemma-4-developer-agent")
if KAGGLE.exists():
    DATA = KAGGLE
WORK = Path("/kaggle/working") if Path("/kaggle/working").exists() else ROOT / "analysis"
API = "http://127.0.0.1:8000/v1"
MODEL = _os.environ.get("LOC_MODEL", "")
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


def chat(messages: list[dict], max_tokens: int = 600) -> str:
    body = {"model": MODEL, "messages": messages, "temperature": 0.0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}, **NO_THINK}
    for attempt in range(4):
        try:
            r = _rq.post(f"{API}/chat/completions", json=body, timeout=600)
            if r.status_code == 400 and "response_format" in body:
                body.pop("response_format")  # guided decoding unavailable: plain JSON prompting instead
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"].get("content") or ""
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                return json.dumps({"error": str(e)[:200]})
            time.sleep(5 * (attempt + 1))
    return "{}"


def parse_json(s: str) -> dict:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return {}


def module_list(ids: list[str], limit: int = 220) -> list[str]:
    mods = Counter(".".join(n.split(".")[:2]) for n in ids if "." in n)
    return [m for m, _ in mods.most_common(limit)]


def signature(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sig = lines[0][:140] if lines else ""
    doc = next((l.strip('"\' ') for l in lines[1:4] if l.startswith(('"""', "'''", '"', "'"))), "")
    return sig + (f"  # {doc[:100]}" if doc else "")


def exp_hypothesis(issue: str, repo: str, ids: list[str]) -> list[str]:
    msgs = [{"role": "system", "content": "You localize bugs in Python repositories. Reply with JSON only."},
            {"role": "user", "content":
             f"Repository: {repo}\nModules (most common first): {', '.join(module_list(ids))}\n\n"
             f"Issue:\n{issue[:6000]}\n\nList up to 10 fully-qualified symbols (module.Class.method or module.function) "
             'in this repository that most likely must be edited to resolve the issue, best first. '
             'JSON: {"symbols": ["..."]}'}]
    out = parse_json(chat(msgs)).get("symbols") or []
    return [s for s in out if isinstance(s, str)][:10]


def exp_rerank(issue: str, cands: list[str], nodes: dict) -> list[str]:
    listing = "\n".join(f"{i}. {c} :: {signature(nodes[c])}" for i, c in enumerate(cands))
    msgs = [{"role": "system", "content": "You localize bugs in Python repositories. Reply with JSON only."},
            {"role": "user", "content":
             f"Issue:\n{issue[:5000]}\n\nCandidate symbols:\n{listing}\n\n"
             "Return the 10 candidates most likely to need editing to resolve the issue, best first, by their numbers. "
             'JSON: {"ranking": [numbers]}'}]
    order = parse_json(chat(msgs, 300)).get("ranking") or []
    picked = [cands[i] for i in order if isinstance(i, int) and 0 <= i < len(cands)]
    return list(dict.fromkeys(picked + cands))


def run_llm(max_workers: int = 8) -> dict:
    tasks = [json.loads(l) for l in (DATA / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if l]
    prepared = []
    for t in tasks:
        key = f"{t['repo'].split('/')[1].lower()}_{t['base_commit']}"
        nodes, ids, emb, adj, index, bm = load_graph(key)
        gold, gold_files = gold_symbols(parse_patch(t["patch"]), nodes)
        if not gold:
            continue
        issue = t["problem_statement"]
        sc = bm.scores(toks(issue))
        r_bm25 = [ids[i] for i in np.argsort(-sc)[:500] if sc[i] > 0]
        r_ident = rank_tokens(extract_identifiers_plus(issue), ids, index)
        prepared.append(dict(t=t, nodes=nodes, ids=ids, emb=emb, adj=adj, index=index, gold=gold,
                             r_bm25=r_bm25, r_ident=r_ident))
    print(f"prepared {len(prepared)} tasks", flush=True)

    def work(p):
        t0 = time.perf_counter()
        hyps = exp_hypothesis(p["t"]["problem_statement"], p["t"]["repo"], p["ids"])
        r_hyp = rank_tokens(hyps, p["ids"], p["index"])
        anchors = (r_hyp or p["r_ident"] or p["r_bm25"])[:3]
        idx = {n: i for i, n in enumerate(p["ids"])}
        sims = p["emb"] @ p["emb"][[idx[a] for a in anchors]].T if anchors else None
        r_emb = [p["ids"][i] for i in np.argsort(-sims.max(axis=1))[:500]] if anchors else []
        fused = rrf([r_hyp, p["r_ident"], p["r_bm25"], r_emb, expand(anchors, p["adj"], 2)])
        reranked_bm25 = exp_rerank(p["t"]["problem_statement"], p["r_bm25"][:50], p["nodes"]) if p["r_bm25"] else []
        reranked_fused = exp_rerank(p["t"]["problem_statement"], fused[:50], p["nodes"]) if fused else []
        return {"id": p["t"]["instance_id"], "repo": p["t"]["repo"], "has_ident": bool(p["r_ident"]),
                "n_hyp": len(hyps), "hyp_resolved": bool(r_hyp), "secs": round(time.perf_counter() - t0, 1),
                "m": {"bm25": metrics(p["r_bm25"], p["gold"]), "hyp": metrics(r_hyp, p["gold"]),
                      "fused_hyp": metrics(fused, p["gold"]), "rerank_bm25_50": metrics(reranked_bm25, p["gold"]),
                      "rerank_fused_50": metrics(reranked_fused, p["gold"])}}

    rows = []
    with _cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for i, r in enumerate(ex.map(work, prepared)):
            rows.append(r)
            if i % 10 == 0:
                print(f"[{i}/{len(prepared)}] last {r['secs']}s", flush=True)

    def agg(sel):
        if not sel:
            return {}
        return {s: {k: round(float(np.mean([r["m"][s][k] for r in sel])), 3) for k in sel[0]["m"][s]} | {"n": len(sel)}
                for s in sel[0]["m"]}
    res = {"model": MODEL, "n": len(rows), "hyp_resolved_rate": round(float(np.mean([r["hyp_resolved"] for r in rows])), 3),
           "all": agg(rows), "with_ident": agg([r for r in rows if r["has_ident"]]),
           "without_ident": agg([r for r in rows if not r["has_ident"]]),
           "mean_secs_per_task": round(float(np.mean([r["secs"] for r in rows])), 1)}
    (WORK / "llm_localization_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    (WORK / "llm_localization_rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return res


def start_vllm() -> None:
    """Same recipe as the official Getting Started notebook: offline wheelhouse + vLLM, tensor parallel over L4s."""
    global MODEL
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
    model_path = "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"
    tp = 4 if torch.cuda.device_count() >= 4 else (2 if torch.cuda.device_count() >= 2 else 1)
    env = dict(_os.environ, VLLM_WORKER_MULTIPROC_METHOD="spawn", VLLM_NO_USAGE_STATS="1",
               PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", VLLM_ENGINE_READY_TIMEOUT_S="1200")
    log = open("/kaggle/working/vllm.log", "w")
    _sp.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", model_path,
               "--served-model-name", "gemma4", "--host", "127.0.0.1", "--port", "8000",
               "--tensor-parallel-size", str(tp), "--max-model-len", "32768", "--gpu-memory-utilization", "0.90",
               "--reasoning-parser", "gemma4"], stdout=log, stderr=_sp.STDOUT, env=env)
    for i in range(240):
        try:
            if _rq.get(f"{API}/models", timeout=5).ok:
                MODEL = "gemma4"
                print(f"vLLM ready after {i * 5}s (tp={tp})", flush=True)
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    log.flush()
    print(Path("/kaggle/working/vllm.log").read_text(errors="replace")[-4000:], flush=True)
    raise RuntimeError("vLLM did not start; see /kaggle/working/vllm.log")


if __name__ == "__main__":
    start_vllm()
    print(json.dumps(run_llm(), indent=1))
