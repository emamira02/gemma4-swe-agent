"""How well do the harness' code-intelligence signals localize the code that the reference fix edits?

For every dev task: derive gold symbols from the reference `patch` (graph nodes whose source contains the
changed lines), then rank all graph nodes with each signal using ONLY the issue text, and report
Recall@k / MRR at symbol and file level. No GPU, no LLM: pure measurement of retrieval signals.

Signals
  ident   identifiers extracted from the issue, resolved like the harness (exact -> suffix -> case-insens. -> substring)
  ident+  ident plus traceback frames, imports and dotted calls inside code blocks
  bm25    BM25 over node id + source text, query = issue text
  emb     cosine neighbours (pre-computed node embeddings) of the top anchors (ident, else bm25)
  graph   1-hop call-graph neighbours of the top anchors;  graph2: 2 hops from ident+ anchors
  rrf     reciprocal-rank fusion of ident, bm25, emb, graph;  rrf+: of ident+, bm25, emb(ident+), graph2
Run: python analysis/localization.py   (expects data/ from scripts/fetch_data.sh)
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KS = (1, 5, 10, 20, 50)
STOP = set("""a an the and or of to in on for with is are be was were it this that as by at from not no can
could should would will may might do does did has have had i we you they he she my our your if then else when
but so use using used get set add new return true false none self cls def class import from print len list dict
str int float bool type object value values key keys item items error errors issue bug fix feature support
example code test tests python version file files function method""".split())
_SPLIT = re.compile(r"[A-Za-z][a-z0-9]*|[0-9]+")


def toks(s: str) -> list[str]:
    return [t.lower() for t in _SPLIT.findall(s.replace("_", " ")) if t.lower() not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.tf = [Counter(d) for d in docs]
        self.ln = np.array([len(d) for d in docs], dtype=float)
        self.avg = self.ln.mean() if len(docs) else 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, q):
        q = [t for t in set(q) if t in self.idf]
        out = np.zeros(len(self.tf))
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.ln[i] / self.avg))
            out[i] = s
        return out


# ---------------- gold symbols from the reference patch ----------------

def parse_patch(patch: str) -> dict[str, list[dict]]:
    files, cur, hunk = {}, None, None
    for line in patch.splitlines():
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            cur = path[2:] if path.startswith("b/") else path
            files.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            hunk = {"removed": [], "context": [], "added": []}
            files[cur].append(hunk)
        elif hunk is not None and cur:
            if line.startswith("-"):
                hunk["removed"].append(line[1:])
            elif line.startswith("+"):
                hunk["added"].append(line[1:])
            elif line.startswith(" "):
                hunk["context"].append(line[1:])
    return files


def is_source(path: str) -> bool:
    p = path.lower()
    return p.endswith(".py") and not re.search(r"(^|/)(tests?|testing|docs|docs_src)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$", p)


def module_candidates(path: str) -> list[str]:
    """Dotted module names a file may appear under in node ids (docs_src/ and src/ prefixes are dropped).
    Single-component suffixes are kept only for top-level files, to avoid spurious matches."""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    cands = [".".join(parts[i:]) for i in range(len(parts)) if len(parts[i:]) >= 2 or len(parts) == 1]
    return cands or [".".join(parts)]


def is_init(path: str) -> bool:
    return path.endswith("__init__.py")


def node_file(nid: str, file_modules: dict[str, str]) -> str | None:
    """Gold file a node belongs to. Package __init__ files only own their direct children."""
    best = None
    for mod, f in file_modules.items():
        if not (nid == mod or nid.startswith(mod + ".")):
            continue
        if is_init(f) and nid.count(".") != mod.count(".") + 1:
            continue
        if best is None or len(mod) > len(best[0]):
            best = (mod, f)
    return best[1] if best else None


def gold_symbols(files: dict, nodes: dict[str, str]) -> tuple[set[str], set[str]]:
    """Per hunk, the most specific node whose source contains the removed lines (or, for pure additions,
    at least two context lines). Test, docs and docs_src files are excluded."""
    gold, gold_files = set(), set()
    for path, hunks in files.items():
        if not is_source(path):
            continue
        gold_files.add(path)
        mods = module_candidates(path)
        cands = {nid: txt for nid, txt in nodes.items() if any(nid.startswith(m + ".") for m in mods)}
        for h in hunks:
            removed = [l.strip() for l in h["removed"] if len(l.strip()) >= 4]
            ctx = [l.strip() for l in h["context"] if len(l.strip()) >= 4]
            hits = []
            for nid, txt in cands.items():
                lines = {l.strip() for l in txt.splitlines()}
                r = sum(1 for l in removed if l in lines)
                c = sum(1 for l in ctx if l in lines)
                if r >= 1 or (not removed and c >= 2):
                    hits.append((r, c, -len(txt), nid))
            if hits:
                hits.sort(reverse=True)
                gold.add(hits[0][3])
    return gold, gold_files


# ---------------- signals ----------------
_IDENT = [re.compile(p) for p in (r"`([^`\n]{2,80})`", r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b",
                                  r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b", r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b",
                                  r"\b([A-Za-z_]\w{2,})\(")]
_TRACE = re.compile(r'File "([^"]+?\.py)", line \d+, in (\w+)')
_CODEBLOCK = re.compile(r"```.*?```", re.S)
_IMPORT = re.compile(r"\bfrom\s+([\w.]+)\s+import\s+\(?([\w, \n]+)\)?")
_CALL = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*\(")


def extract_identifiers(text: str) -> list[str]:
    seen = Counter()
    for rx in _IDENT:
        for m in rx.finditer(text):
            tok = m.group(1).strip().strip("()").split("(")[0]
            for t in re.split(r"[\s,]+", tok):
                t = t.strip(".:;'\"")
                if len(t) >= 3 and t.lower() not in STOP and not t.isdigit():
                    seen[t] += 1
    return [t for t, _ in seen.most_common()]


def extract_identifiers_plus(text: str) -> list[str]:
    """Baseline extraction + traceback frames, imports and dotted calls inside code blocks (weighted)."""
    score = Counter()
    for path, fn in _TRACE.findall(text):
        score[fn] += 3
        mods = module_candidates(path.replace("\\", "/").split("site-packages/")[-1])
        if mods:
            score[f"{mods[0]}.{fn}"] += 3
    for block in _CODEBLOCK.findall(text):
        for mod, names in _IMPORT.findall(block):
            for n in re.split(r"[,\s]+", names):
                if n and n != "as":
                    score[f"{mod}.{n}"] += 2
        for call in _CALL.findall(block):
            score[call] += 1
    for i, tok in enumerate(extract_identifiers(text)):
        score[tok] += 1 + 1.0 / (1 + i)
    return [t for t, _ in score.most_common() if len(t) >= 3 and t.lower() not in STOP]


def resolve(tok: str, ids: list[str], last: dict[str, list[str]]) -> list[tuple[int, str]]:
    if tok in last.get("__all__", ()):  # exact id
        return [(0, tok)]
    out = []
    tail = tok.split(".")[-1]
    for nid in last.get(tail, []):
        if nid.endswith("." + tok) or nid == tok or nid.split(".")[-1] == tok:
            out.append((1, nid))
    if out:
        return out
    low = tail.lower()
    out = [(2, nid) for nid in last.get("__lower__" + low, [])]
    if out or len(tail) < 5:
        return out
    return [(3, nid) for nid in ids if low in nid.split(".")[-1].lower()][:50]


def rank_tokens(tokens: list[str], ids: list[str], index: dict) -> list[str]:
    scored = defaultdict(float)
    for pos, tok in enumerate(tokens[:40]):
        hits = resolve(tok, ids, index)
        if not hits:
            continue
        w = 1.0 / (1 + math.log1p(len(hits))) / (1 + 0.05 * pos)
        for tier, nid in hits:
            scored[nid] += w * (1.0, 0.8, 0.5, 0.2)[tier]
    return [n for n, _ in sorted(scored.items(), key=lambda x: -x[1])]


def rrf(lists: list[list[str]], k: int = 60) -> list[str]:
    s = defaultdict(float)
    for lst in lists:
        for r, n in enumerate(lst[:200]):
            s[n] += 1.0 / (k + r + 1)
    return [n for n, _ in sorted(s.items(), key=lambda x: -x[1])]


def expand(anchors: list[str], adj: dict, hops: int) -> list[str]:
    out, frontier = list(anchors), list(anchors)
    for _ in range(hops):
        nxt = []
        for n in frontier:
            for m in sorted(adj.get(n, ())):
                if m not in out:
                    out.append(m)
                    nxt.append(m)
        frontier = nxt
    return out


def hop_distance(anchors: list[str], gold: set[str], adj: dict, max_d: int = 4) -> int | None:
    """Undirected call-graph distance from the nearest anchor to the nearest gold symbol (None = beyond max_d)."""
    frontier, seen = set(anchors), set(anchors)
    for d in range(max_d + 1):
        if frontier & gold:
            return d
        nxt = {m for n in frontier for m in adj.get(n, ())} - seen
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return None


def metrics(ranked: list[str], gold: set[str]) -> dict:
    out = {f"R@{k}": float(bool(gold & set(ranked[:k]))) for k in KS}
    out["MRR"] = next((1.0 / (i + 1) for i, n in enumerate(ranked) if n in gold), 0.0)
    return out


def file_metrics(ranked: list[str], file_modules: dict) -> dict:
    hit = next((i for i, n in enumerate(ranked) if node_file(n, file_modules)), None)
    return {f"R@{k}": float(hit is not None and hit < k) for k in KS} | {"MRR": 1.0 / (hit + 1) if hit is not None else 0.0}


def load_graph(key: str):
    g = json.loads((DATA / "graphs" / f"{key}.json").read_text(encoding="utf-8"))
    nodes = {n["id"]: n.get("text") or "" for n in g["nodes"]}
    ids = list(nodes)
    with np.load(DATA / "embeddings" / f"{key}.npz", allow_pickle=False) as z:
        emb = np.stack([z[i] for i in ids]).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    adj = defaultdict(set)
    for e in g["edges"]:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    index = {"__all__": set(ids)}
    for nid in ids:
        tail = nid.split(".")[-1]
        index.setdefault(tail, []).append(nid)
        index.setdefault("__lower__" + tail.lower(), []).append(nid)
    bm = BM25([toks(nid.replace(".", " ")) * 2 + toks(nodes[nid]) for nid in ids])
    return nodes, ids, emb, adj, index, bm


def run() -> dict:
    tasks = [json.loads(l) for l in (DATA / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if l]
    rows, coverage, cache, t0 = [], Counter(), {}, time.perf_counter()
    for ti, t in enumerate(tasks):
        if ti % 10 == 0:
            print(f"[{ti}/{len(tasks)}] {time.perf_counter() - t0:.0f}s", file=sys.stderr, flush=True)
        key = f"{t['repo'].split('/')[1].lower()}_{t['base_commit']}"
        if key not in cache:
            cache = {key: load_graph(key)}  # one graph in memory at a time
        nodes, ids, emb, adj, index, bm = cache[key]
        gold, gold_files = gold_symbols(parse_patch(t["patch"]), nodes)
        coverage["tasks"] += 1
        coverage["with_source_change"] += bool(gold_files)
        coverage["with_gold_symbol"] += bool(gold)
        if not gold_files:
            continue
        issue = t["problem_statement"]
        r_ident = rank_tokens(extract_identifiers(issue), ids, index)
        r_identp = rank_tokens(extract_identifiers_plus(issue), ids, index)
        sc = bm.scores(toks(issue))
        r_bm25 = [ids[i] for i in np.argsort(-sc)[:500] if sc[i] > 0]
        idx = {n: i for i, n in enumerate(ids)}

        def emb_from(anchors: list[str]) -> list[str]:
            if not anchors:
                return []
            sims = emb @ emb[[idx[a] for a in anchors]].T
            return [ids[i] for i in np.argsort(-sims.max(axis=1))[:500]]

        anchors, anchors_p = (r_ident or r_bm25)[:3], (r_identp or r_bm25)[:3]
        lists = {"ident": r_ident, "ident+": r_identp, "bm25": r_bm25, "emb": emb_from(anchors),
                 "graph": expand(anchors, adj, 1), "graph2": expand(anchors_p, adj, 2)}
        lists["rrf"] = rrf([lists["ident"], lists["bm25"], lists["emb"], lists["graph"]])
        lists["rrf+"] = rrf([lists["ident+"], lists["bm25"], emb_from(anchors_p), lists["graph2"]])
        file_modules = {m: f for f in gold_files for m in module_candidates(f)}
        rows.append({"repo": t["repo"], "has_ident": bool(r_ident), "has_ident+": bool(r_identp), "gold": bool(gold),
                     "sym": {k: metrics(v, gold) for k, v in lists.items()} if gold else {},
                     "file": {k: file_metrics(v, file_modules) for k, v in lists.items()},
                     "hop": hop_distance(anchors_p, gold, adj) if gold else "n/a"})
    coverage["issue_has_resolvable_identifier"] = sum(r["has_ident"] for r in rows)
    coverage["issue_has_resolvable_identifier_plus"] = sum(r["has_ident+"] for r in rows)

    def agg(sel: list[dict], level: str) -> dict:
        sel = [r for r in sel if r[level]]
        if not sel:
            return {}
        return {sig: {m: round(float(np.mean([r[level][sig][m] for r in sel])), 3) for m in sel[0][level][sig]} | {"n": len(sel)}
                for sig in sel[0][level]}

    focus = ("bm25", "rrf+")
    by_repo = {}
    for repo in sorted({r["repo"] for r in rows}):
        sel = [r for r in rows if r["repo"] == repo]
        by_repo[repo] = {"n_tasks": len(sel),
                         "symbol": {s: v for s, v in agg(sel, "sym").items() if s in focus},
                         "file": {s: v for s, v in agg(sel, "file").items() if s in focus}}
    hops = Counter(str(r["hop"]) for r in rows if r["gold"])
    return {"coverage": dict(coverage),
            "symbol_level": agg(rows, "sym"), "file_level": agg(rows, "file"),
            "symbol_level_by_identifier_presence": {"with_ident+": agg([r for r in rows if r["has_ident+"]], "sym"),
                                                    "without_ident+": agg([r for r in rows if not r["has_ident+"]], "sym")},
            "hop_distance_anchor_to_gold": dict(sorted(hops.items())),
            "by_repo": by_repo}




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
