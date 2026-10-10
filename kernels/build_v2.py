"""Inline the locstudy package (dependency order, relative imports stripped) + analysis/llm_v2.py into one Kaggle script."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["__init__", "signals", "gold", "data", "metrics", "study"]
REL_IMPORT = re.compile(r"^\s*from \.\w* import [^\n]*\n(?:\s+[^\n]*\n)*?", re.M)
parts = ["from __future__ import annotations\n"]
for mod in ORDER:
    src = (ROOT / "locstudy" / f"{mod}.py").read_text(encoding="utf-8")
    src = src.replace("from __future__ import annotations\n", "")
    # drop relative imports, including parenthesised multi-line ones
    src = re.sub(r"^[ \t]*from \.\w* import \([^)]*\)\n", "", src, flags=re.M)
    src = re.sub(r"^[ \t]*from \.\w* import [^\n]*\n", "", src, flags=re.M)
    src = re.sub(r"^[ \t]*from \. import [^\n]*\n", "", src, flags=re.M)
    parts.append(f"\n# ======== locstudy/{mod}.py ========\n{src}")
parts.append("\n# ======== analysis/llm_v2.py ========\n" + (ROOT / "analysis" / "llm_v2.py").read_text(encoding="utf-8"))
out = ROOT / "kernels" / "llm-localization" / "run_llm_localization.py"
out.write_text("".join(parts), encoding="utf-8")
compile(out.read_text(encoding="utf-8"), str(out), "exec")
print(f"wrote {out} ({out.stat().st_size} bytes), compiles OK")
