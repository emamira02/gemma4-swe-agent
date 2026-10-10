"""Label-quality audit: categorise every hunk as mapped/unmapped and every header disagreement, with a seeded sample
for manual inspection. Output: results/label_audit.json (counts) + results/private/label_audit_samples.md (examples)."""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

from .data import load_graph, load_tasks
from .gold import _HEADER_NAME, _signal_lines, is_source, module_candidates, parse_patch


def classify_unmapped(h, cands: dict[str, str]) -> str:
    removed = [l.strip() for l in h.removed if len(l.strip()) >= 4]
    if not removed:
        if all(not l.strip() or l.lstrip().startswith(("import ", "from ", "#", "@")) for l in h.added):
            return "pure addition: imports, comments or decorators"
        if any(re.match(r"\s*(async\s+def|def|class)\s", l) for l in h.added):
            return "pure addition: new def or class"
        return "pure addition: other module-level code"
    if all(l.startswith(("import ", "from ", "#")) for l in removed):
        return "edit: imports or comments"
    if not any(l in t for t in cands.values() for l in removed):
        return "edit: module-level code outside any symbol"
    return "edit: lines not matched (whitespace or duplication)"


def header_disagreement_kind(header_name: str, gold_sym: str, h, nodes: dict[str, str]) -> str:
    parts = gold_sym.split(".")
    if any(header_name.lower() == p.lower() for p in parts):
        return "case-only"
    if any(re.search(rf"\b(def|class)\s+{re.escape(header_name)}\b", l) for l in h.context + h.removed):
        return "header names a symbol inside the hunk (git context = previous def)"
    return "header names the preceding top-level def or class (git funcname heuristic)"


def run(data_dir: Path, out_dir: Path, sample: int = 25, seed: int = 0, min_cov: float = 0.5) -> dict:
    counts, kinds, examples = Counter(), Counter(), []
    for t in load_tasks(data_dir):
        g = load_graph(str(data_dir), t.graph_key)
        for path, hunks in parse_patch(t.patch).items():
            if not is_source(path):
                continue
            mods = module_candidates(path)
            cands = {n: g.nodes[n] for n in g.ids if any(n.startswith(m + ".") for m in mods)}
            for h in hunks:
                removed, ctx = _signal_lines(h.removed), _signal_lines(h.context)
                best = None
                for nid, txt in cands.items():
                    lines = {l.strip() for l in txt.splitlines()}
                    r, c = sum(l in lines for l in removed), sum(l in lines for l in ctx)
                    if (removed and r >= 1 and r / len(removed) >= min_cov) or (not removed and c >= 2):
                        key = (r, c, -len(txt), nid)
                        best = key if best is None or key > best else best
                if best is None:
                    kind = classify_unmapped(h, cands)
                    counts["unmapped"] += 1
                    kinds["unmapped: " + kind] += 1
                    continue
                counts["mapped"] += 1
                m = _HEADER_NAME.search(h.header)
                if not m:
                    continue
                counts["header_checked"] += 1
                if m.group(1) in best[3].split("."):
                    counts["header_agree"] += 1
                    continue
                kind = header_disagreement_kind(m.group(1), best[3], h, g.nodes)
                kinds["disagree: " + kind] += 1
                examples.append({"task": t.instance_id, "file": path, "header": h.header, "gold": best[3], "kind": kind,
                                 "removed": h.removed[:3], "context": h.context[:3]})
    res = {"counts": dict(counts), "kinds": dict(kinds.most_common())}
    (out_dir / "label_audit.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    rnd = random.Random(seed)
    pick = rnd.sample(examples, min(sample, len(examples)))
    md = ["# Label audit samples (seeded; private: contains code excerpts)\n"]
    for e in pick:
        md += [f"## {e['task']} · {e['file']}", f"- @@ header: `{e['header']}`", f"- gold: `{e['gold']}`",
               f"- kind: {e['kind']}", f"- removed: {e['removed']}", f"- context: {e['context']}", ""]
    (out_dir / "private").mkdir(parents=True, exist_ok=True)
    (out_dir / "private" / "label_audit_samples.md").write_text("\n".join(md), encoding="utf-8")
    return res
