# Where Is the Bug? Measuring Graph, Embedding and Lexical Signals for Issue Localization in Offline SWE Agents

*Draft v0.1 — Gemma 4 Developer Agent paper track. Every number comes from `analysis/localization_results.json`; placeholders `[__]` are filled only from logged runs.*

## Abstract (≤150 words, write last)
[__]

## 1. Introduction
Small, offline coding agents fail less often at *writing* a patch than at *finding where to write it*. The Gemma 4 Developer Agent harness gives a 31B quantized model three code-intelligence tools — `search_similar_code` over pre-computed node embeddings, and `get_code_neighbors` / `get_code_subgraph` over a call graph — under a tight budget (≈ 6 minutes per task on the hidden set). These tools are only as useful as the anchors an agent can feed them: `search_similar_code` resolves its query against **symbol names**, not free text.

We ask a narrow, measurable question before training anything: **given only the issue text, how often does each available signal surface the symbols that the reference fix actually edits, and how should they be combined?** We answer it on the 129 public development tasks without a GPU or an LLM, so every agent design choice downstream can rest on numbers rather than intuition.

Contributions:
1. A reproducible protocol that derives *gold symbols* from reference patches and maps them onto the harness' graph nodes (coverage reported).
2. A measurement of identifier, lexical (BM25), embedding-neighbour and graph-expansion signals at symbol and file level (Recall@k, MRR).
3. Evidence on *anchor availability* — how often an issue names a resolvable symbol at all — and on how far, in call-graph hops, the edit lies from the best anchor.
4. A fused localization policy (reciprocal-rank fusion) and its budget-aware form as an ADK skill for the agent.

## 2. Setup
**Data.** 129 tasks from fastapi (67), rich (48), requests (13), httpx (1); each has an issue, the base commit, a reference `patch` and a `test_patch`. Per commit the harness ships a call graph (nodes: fully qualified symbols with source text; edges: `calls`) and 256-d node embeddings.

**Gold symbols.** For each non-test, non-docs source file in the reference patch and each hunk, the gold symbol is the most specific node whose source contains the hunk's removed lines (pure additions: ≥ 2 context lines). Files: 126 of 129 tasks touch source code; gold symbols are recovered for 115.

**Signals (issue text only).**
- *ident*: identifiers from back-ticks, dotted names, CamelCase, snake_case and calls, resolved like the harness (exact → suffix → case-insensitive → substring) and ranked by match tier and specificity. *ident+* adds traceback frames, imports and dotted calls from code blocks.
- *bm25*: BM25 over node id tokens (×2) + source tokens, query = issue tokens.
- *emb*: cosine neighbours of the top-3 anchors in the provided embedding space (anchors = ident, else bm25).
- *graph*: 1-hop call-graph neighbours of the anchors; *graph2*: 2 hops from ident+ anchors.
- *rrf / rrf+*: reciprocal-rank fusion (k = 60) of the above.

**Metrics.** Symbol-level Recall@{1,5,10,20,50} and MRR over tasks with gold symbols; file-level the same, counting the first node that lives in a gold file.

## 3. Results (run of 2026-10-10, `analysis/localization_results.json`)
Coverage: 126/129 tasks change source code; gold symbols recovered for 115.

**Table 1 — symbol level (n = 115).**

| Signal | R@1 | R@5 | R@10 | R@20 | R@50 | MRR |
|---|---|---|---|---|---|---|
| ident | .183 | .235 | .252 | .252 | .270 | .206 |
| bm25 | .130 | .261 | .304 | .417 | **.687** | .207 |
| emb | .130 | .261 | .270 | .304 | .339 | .188 |
| graph (1 hop) | **.191** | .278 | .304 | .304 | .313 | .232 |
| graph2 (2 hops) | .148 | .278 | .304 | .357 | .417 | .214 |
| rrf | .174 | **.330** | .365 | .426 | .548 | **.245** |
| rrf+ | .165 | **.330** | **.374** | **.452** | .557 | .240 |

**Table 2 — file level (n = 126).** graph reaches R@5 = .516; rrf reaches R@20 = .651; bm25 reaches R@50 = .849.

**Table 3 — split by anchor availability (symbol level).**

| Subset | n | best R@5 | best R@20 | bm25 R@50 |
|---|---|---|---|---|
| issue names a resolvable symbol | 59 | .559 (rrf) | .729 (rrf+) | .814 |
| issue names none | 56 | .107 (rrf+) | .214 (bm25) | .554 |

## 4. Analysis
- **Anchor availability decides localization.** Only 65 of 126 issues (52 %) name a symbol that resolves in the graph. With an anchor, fused retrieval puts the edited symbol in the top-5 for 56 % of tasks; without one, every signal except deep BM25 collapses (R@5 ≤ .11). Embedding and graph tools inherit their anchors' quality — they cannot rescue an anchor-free issue.
- **Fusion helps at the top, lexical search at depth.** RRF lifts R@5 from .278 (best single signal) to .330; BM25 alone is best at R@50 (.687).
- **Richer extraction did not help here.** Adding traceback frames, imports and code-block calls (ident+) left anchor coverage unchanged (65) and lowered R@1 (.183 → .139): extra tokens are mostly user code. Negative result, reported as such.
- **The call graph is sparse.** Hop distance from the nearest anchor to the edit: 0 hops for 30 tasks, 1 for 7, 2 for 19, 3 for 12, 4 for 20, and > 4 or unreachable for 27 (115 tasks). One-hop expansion captures little beyond the anchor itself; useful context often sits 2–4 hops away.
- **Repositories differ.** On rich (48 tasks) rrf+ doubles BM25's R@5 (.302 vs .163); on requests (13) .583 vs .333; on fastapi (64) BM25 is marginally ahead (.305 vs .288).

## 5. From measurement to agent design
A two-mode localization policy follows directly:
1. **Anchored mode** (issue names a resolvable symbol): fused retrieval (identifier resolution + BM25 + embedding neighbours + graph), read the top-5 candidates first.
2. **Anchor-free mode**: the agent's first step must *create* anchors — BM25 top-50 candidates (55 % contain the edit) re-ranked by the model reading only signatures/docstrings, or model-hypothesised symbol names resolved through `get_code_neighbors`' fuzzy resolution — before spending budget on reads.
Next measurements (with the model in the loop): anchor-hypothesis accuracy, re-ranking gain on BM25 top-50, and end-to-end pass rate per mode.

## 6. Limitations
Dev repos only (the hidden set uses private repositories); gold symbols approximate the edited region; no execution-based signal (tests, tracebacks produced by running code) is measured here.

## 7. Reproducibility
`scripts/fetch_data.sh` (subset download) → `python analysis/localization.py`. No competition data is redistributed.
