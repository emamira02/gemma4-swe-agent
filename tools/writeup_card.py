"""Kaggle Writeup card (1120x560): title plus Hit@5 by anchor stratum, read from the result files.

Usage: python tools/writeup_card.py . paper/figures/writeup_card.png
"""
import json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

repo, out = sys.argv[1], sys.argv[2]
s = json.load(open(f"{repo}/results/summary.json"))
l = json.load(open(f"{repo}/results/llm_summary.json"))
def get(d, path):
    for k in path.split("/"):
        d = d[k]
    return d[0] if isinstance(d, list) else d
rows = [("Anchored", get(s, "by_anchor/named_symbol/bm25/R@5"), get(l, "named_symbol/rerank50/R@5")),
        ("Anchor-free", get(s, "by_anchor/no_named_symbol/bm25/R@5"), get(l, "no_named_symbol/rerank50/R@5"))]
fig = plt.figure(figsize=(5.6, 2.8), dpi=200)
fig.patch.set_facecolor("white")
fig.text(0.05, 0.84, "Anchored or Not", fontsize=19, weight="bold", color="#1a1a1a")
fig.text(0.05, 0.73, "Localization and re-ranking in an offline Gemma 4 agent", fontsize=8.5, color="#444")
ax = fig.add_axes([0.17, 0.14, 0.78, 0.48])
y = [1, 0]
ax.barh([v + 0.17 for v in y], [100 * r[1] for r in rows], height=0.32, color="#9aa5b1", label="BM25")
ax.barh([v - 0.17 for v in y], [100 * r[2] for r in rows], height=0.32, color="#1f6feb", label="Gemma 4 re-rank")
for v, r in zip(y, rows):
    ax.text(100 * r[1] + 1, v + 0.17, f"{100*r[1]:.1f}%", va="center", fontsize=7, color="#444")
    ax.text(100 * r[2] + 1, v - 0.17, f"{100*r[2]:.1f}%", va="center", fontsize=7, color="#1f6feb", weight="bold")
ax.set_yticks(y, [r[0] for r in rows], fontsize=8)
ax.set_xlim(0, 100)
ax.set_xlabel("Hit@5: an edited symbol in the top 5 (114 tasks)", fontsize=7)
ax.tick_params(axis="x", labelsize=6.5)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.legend(fontsize=6.5, frameon=False, loc="lower right")
fig.savefig(out, dpi=200)
print([(r[0], round(100*r[1], 1), round(100*r[2], 1)) for r in rows])
