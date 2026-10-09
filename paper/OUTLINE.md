# Paper outline — Gemma 4 Developer Agent paper track (≤ 3,000 words, due 12 Nov 2026 23:59 UTC)

Judging (official, equal weight 0–5): Novelty · Quality/generality · Relevance · Verifiability · Clarity.

1. **Title** — Hybrid Graph-Retrieval Localization for Small Offline SWE Agents (working title)
2. **Abstract** — problem, method, measured gain (fill only with real numbers)
3. **Introduction** — why localization dominates failure for single-accelerator models; contribution list
4. **Method** — dense → graph expansion → lexical confirmation → re-rank; ADK config + skills; budget policy
5. **Experiments** — E0–E4 ablation; metrics: pass rate, Recall@k/MRR of gold-edited files, budget/issue
6. **Error analysis** — failure taxonomy (wrong file, right file wrong hunk, test env, budget exhaustion)
7. **Related work** — SWE-bench agents, code retrieval, GraphRAG
8. **Reproducibility** — public notebook, config hash per result, seeds
9. **Limitations**

Rule: no claim without a logged run in `runs.csv`.
