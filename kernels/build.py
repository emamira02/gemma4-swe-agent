"""Build the single-file Kaggle script: analysis/localization.py (without its __main__ block) + analysis/llm_experiments.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
base = (ROOT / "analysis" / "localization.py").read_text(encoding="utf-8")
base = base[: base.index('if __name__ == "__main__":')]
exp = (ROOT / "analysis" / "llm_experiments.py").read_text(encoding="utf-8")
out = ROOT / "kernels" / "llm-localization" / "run_llm_localization.py"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(base + "\n\n" + exp, encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size} bytes)")
