"""Per-call evidence for the tool-call serialization failure behind malformed edit_file / write_file calls.

    python -m analysis.serialization_audit [--out results/serialization_audit.json]

Inputs: results/kaggle_eval_<tag>/agent_eval/results/traces/*.json of the two eras that used tools with several
code-valued string arguments (failure_audit.ERAS: edit_file = S1-S5, public_prompt = B1). Output: counts only (no
argument text, no task text).

Mechanism under test (vLLM gemma4 parser, read in its source; template sorts argument keys): a string value ends
only at the dedicated <|"|> token, and arguments come out in alphabetical order, so a value the model closes with
a backtick or a plain quote runs on and swallows every later argument. Signature per call: a required argument is
missing and its own key text ("old_string:") appears inside an earlier argument's value. Also counted: whether the
parsed key order of well-formed calls is alphabetical (the parser keeps emission order), and the character just
before the swallowed key.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from analysis.failure_audit import ERAS, REQUIRED, ROOT

TOOLS = ("edit_file", "write_file")
CLOSERS = {"`": "backtick", '"': "double_quote", "'": "single_quote"}


def call_facts(name: str, args: dict) -> dict:
    """Signature of one call: missing required keys, which of them sit inside another value, and the closer before."""
    missing = sorted(REQUIRED[name] - set(args))
    found, closers = [], []
    for k in missing:
        for v in args.values():
            m = isinstance(v, str) and re.search(rf"(?<!\w){re.escape(k)}\s*:", v)
            if m:
                found.append(k)
                head = v[:m.start()].rstrip(" ,{\n\t")  # text before the swallowed key, separators dropped
                closers.append(CLOSERS.get(head[-1:], "other") if head else "start")
                break
    known = [k for k in args if k in REQUIRED[name] or k == "allow_multiple"]
    return {"missing": missing, "found": found, "closers": closers,
            "alphabetical": known == sorted(known) and len(known) == len(args)}


def audit_tags(tags: tuple[str, ...], results: Path) -> dict:
    c, closers = Counter(), Counter()
    for tag in tags:
        for f in sorted((results / f"kaggle_eval_{tag}" / "agent_eval" / "results" / "traces").glob("trace_*.json")):
            for s in json.loads(f.read_text(encoding="utf-8"))["steps"]:
                for tc in s.get("tool_calls") or []:
                    name = tc["function_name"]
                    if name not in TOOLS:
                        continue
                    x = call_facts(name, tc["arguments"])
                    c[f"{name}/calls"] += 1
                    if x["missing"]:
                        c[f"{name}/missing_required"] += 1
                        c[f"{name}/missing_found_in_value"] += len(x["found"]) == len(x["missing"])
                        closers.update(f"{name}/{k}" for k in x["closers"])
                    else:
                        c[f"{name}/well_formed"] += 1
                        c[f"{name}/well_formed_alphabetical"] += x["alphabetical"]
    out = {}
    for key, v in c.items():
        tool, _, field = key.partition("/")
        out.setdefault(tool, {})[field] = v
    for key, v in closers.items():
        tool, _, closer = key.partition("/")
        out.setdefault(tool, {}).setdefault("closer_before_swallowed_key", {})[closer] = v
    return out


def build(results: Path) -> dict:
    eras = {era: ERAS[era] for era in ("edit_file", "public_prompt")}
    return {"eras": {era: {"tags": list(tags), **audit_tags(tags, results)} for era, tags in eras.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=ROOT / "results")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "serialization_audit.json")
    a = ap.parse_args()
    doc = build(a.results)
    a.out.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    print(json.dumps(doc, indent=1))


if __name__ == "__main__":
    main()
