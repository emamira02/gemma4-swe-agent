<!-- AUTO-GENERATED from PAPER.template.md + results/*.json -->
# Anchors Decide: Measuring Code-Intelligence Signals for Issue Localization in Offline SWE Agents

*Gemma 4 Developer Agent — paper track. All numbers are filled automatically from `results/*.json` (`python -m locstudy all`); none are typed by hand.*

## Abstract
An offline 31B agent with roughly six minutes per issue must find *where* to edit before it can edit. We measure, without any model in the loop, how well the harness' code-intelligence signals — identifier resolution, call-graph expansion, pre-computed embedding neighbours — and plain BM25 recover the symbols that reference fixes actually change, on the 129 public development tasks. Labels are derived from patches with a strict, audited rule; every estimate carries a task-level bootstrap interval and paired comparisons are corrected for multiplicity. Three findings shape agent design. (1) **Anchors decide:** when the issue names a resolvable symbol (58 tasks), reciprocal-rank fusion puts an edited symbol in the top 5 for 53.4% [41.4, 65.5] of tasks; when it names none (56 tasks) every structure-based signal collapses and only deep lexical search remains useful. (2) **Fusion must be mode-dependent:** without anchors, BM25 alone finds an edited symbol in the top 50 for 55.4% [42.9, 67.9] of tasks versus 28.6% [17.9, 41.1] for fusion (paired Holm p = 0.001). (3) **A reading budget erases fusion's advantage:** within 8k tokens of reading, fusion and BM25 are statistically indistinguishable.

## 1. Introduction
The Gemma 4 Developer Agent harness offers three code-intelligence tools — `search_similar_code` over pre-computed node embeddings, `get_code_neighbors` and `get_code_subgraph` over a call graph — alongside shell and file tools, under tight budgets (≈ 6 min per hidden task, 32k-token context). `search_similar_code` resolves its query against **symbol names**, not free text: the tools are only as good as the anchors an agent can give them.

Before spending GPU hours on prompting or fine-tuning, we ask a measurable question: *given only the issue text, how often does each signal surface a symbol that the reference fix edits, at what reading cost, and how should signals be combined?* We contribute:
1. a reproducible labelling protocol mapping reference patches onto the harness' graph nodes, with a quantified label-quality audit;
2. a symbol- and file-level measurement of identifier, lexical, embedding and graph signals with bootstrap intervals and Holm-corrected paired tests;
3. a **reading-budget metric** (tokens read until the first edited symbol) that reflects the agent's real constraint;
4. design rules for a two-mode localization policy, released as code.

## 2. Setting and data
The dev set has 129 tasks from fastapi, rich, requests and httpx; 126 change non-test, non-documentation source. Each commit ships a call graph (nodes are fully qualified symbols with source text; edges are `calls`) and 256-d node embeddings. The hidden test set (≈ 120 tasks) comes from private repositories, so we favour conclusions about *signal types* over repository-specific tuning.

## 3. Method
**Gold symbols.** For each hunk in a source file of the reference patch, the gold symbol is the most specific node containing at least half of the hunk's removed lines, ignoring imports and comments (pure additions: ≥ 2 context lines). The 50 % threshold was fixed before analysis. 425 of 660 hunks map to a node; the rest are module-level edits — imports or comments (62), module-level code outside any symbol (57) and additions of new module-level code, imports or definitions — which no symbol-level signal can point to. 114 tasks have at least one gold symbol.

**Label audit.** For 267 of 290 mapped edit hunks, *all* removed lines lie inside the chosen symbol. We also compared labels with the enclosing name in git's `@@` hunk header: they agree on 262 of 419 hunks, but 154 of the disagreements are git's funcname heuristic naming the *preceding* top-level definition (sometimes a code example inside a docstring), not label errors; seeded samples confirmed this by inspection. The header is therefore a weak proxy and the coverage statistic our primary label-quality measure.

**Signals (issue text only).** *Identifiers*: back-ticked names, dotted names, CamelCase, snake_case and calls, resolved like the harness (exact → dotted suffix → case-insensitive → substring) and ranked by match tier and specificity; *Identifiers+* adds traceback frames, imports and calls from code blocks. *BM25* indexes node-id tokens (double weight) and source. *Embedding neighbours* and *graph expansion* (1 or 2 hops) start from the top-3 anchors (identifiers, else BM25). *RRF* and *RRF+* fuse the lists by reciprocal rank (k = 60).

**Metrics.** Recall@k is the share of tasks with an edited symbol among the first k; MRR uses the first such rank. File-level variants count any symbol of an edited file. **Reading budget**: tokens (≈ characters/4) of full source an agent reads walking the ranking until the first edited symbol; we report Hit@{2k, 8k, 32k} and the median.

**Inference.** 95 % percentile intervals from 10,000 task-level bootstrap resamples (seed 0); paired comparisons of the primary method (RRF+) against every other signal use exact McNemar tests with Holm correction, plus paired-bootstrap intervals for the difference. Parameters (k = 60, three anchors, BM25 k1 = 1.2, b = 0.75, 50 % label coverage) were fixed in advance and varied one at a time in a sensitivity analysis.

## 4. Results
**4.1 Overall.** Across 114 tasks, RRF+ ranks an edited symbol in the top 5 for 32.5% [23.7, 41.2] of tasks and in the top 20 for 44.7% [36.0, 53.5]. BM25 is the best single signal in depth (top 50: 68.4% [59.7, 77.2]); graph expansion and RRF share the highest top-1 rate (16.7% [9.7, 23.7] and 16.7% [9.7, 23.7]). At file level, one-hop graph expansion finds an edited file in the top 5 for 50.8% [42.1, 59.5] (Tables 1–3 in RESULTS.md).

**4.2 Anchors decide.** 65 of 126 source-changing issues name a symbol that resolves in the graph. With such an anchor, RRF+ reaches 53.4% [41.4, 65.5] at top-5 and 72.4% [60.3, 82.8] at top-20. Without one, RRF+ falls to 10.7% [3.6, 19.6] at top-5; embedding neighbours (7.1% [1.8, 14.3]) and one-hop graph expansion (8.9% [1.8, 17.9]) barely improve even at top-50: in this mode their anchors are BM25's top results, and BM25's own top-5 contains an edited symbol for only 8.9% [1.8, 17.9] of these tasks (Figure 1). Richer extraction from tracebacks and code blocks did not create new anchors on these issues: Identifiers+ matches Identifiers.

**4.3 Fusion must be mode-dependent.** In the anchor-free subset, BM25 alone recovers an edited symbol within the top 50 for 55.4% [42.9, 67.9] of tasks, whereas RRF+ reaches only 28.6% [17.9, 41.1] — a paired difference of 26.8% (95 % CI 14.2% to 41.1%; Holm p = 0.001). Fusing lists that inherit bad anchors dilutes the one signal that still works.

**4.4 A reading budget erases fusion's advantage.** Within 8k tokens of reading, BM25 reaches an edited symbol for 50.9% [42.1, 59.7] of tasks, RRF+ for 45.6% [36.8, 54.4] and RRF for 41.2% [32.5, 50.0]; the paired difference RRF+ − BM25 is -5.3% (95 % CI -14.0% to 3.5%; Holm p = 0.534). Fusion's hits also arrive later in reading cost (a plausible cause, larger symbols ranked early, is not measured here): median reading cost to the first edited symbol is 6,464 tokens for RRF+, 4,991 for BM25 and 646 for graph expansion when it succeeds. Rank-based recall overstates fusion's practical value for a budgeted agent.

**4.5 How confident are the differences?** RRF+ significantly beats identifiers, embedding neighbours and one-hop graph expansion at top-20 (Holm-adjusted p = 0.000 vs graph). Its advantage over BM25 at top-5 — 7.0% (95 % CI -1.8% to 15.8%; Holm p = 0.303) — is **not** statistically reliable at this sample size. We therefore claim mode dependence and budget effects, not a universal winner.

**4.6 Graph distance.** From the nearest anchor, the edited symbol is the anchor itself in 28 tasks, 1 hop away in 8, 2 in 18, 3 in 12, 4 in 21 and unreachable within 4 hops in 27 (Figure 2). The `calls`-only graph is sparse: expansion beyond one hop must be budgeted, not exhaustive.

**4.7 Robustness.** Results are stable to the pre-registered choices: RRF+ top-5 recall is 30.7% with k = 10 and 31.6% with k = 100, 29.8% with BM25 (0.9, 0.4), and 33.0% / 32.4% with lenient / maximal label strictness. Using a single anchor instead of three lowers it to 27.2%. Per repository (top-5), fusion helps on rich (RRF+ 30.2% [16.3, 44.2] vs BM25 16.3% [7.0, 27.9]) and requests (58.3% [33.3, 83.3] vs 33.3% [8.3, 58.3], only 12 tasks) but not on fastapi (27.6% [17.2, 39.7] vs 29.3% [17.2, 41.4]): repository style matters, another reason to prefer mode rules over tuned weights.

## 5. Implications for agent design
1. **Detect the mode first.** Resolve identifiers from the issue in one cheap step; whether any resolve predicts localization difficulty better than any retrieval score.
2. **Anchored mode:** fuse identifiers, BM25, embedding neighbours and graph expansion; read the top-5 symbols first.
3. **Anchor-free mode:** do not fuse structure-based lists; walk BM25 deep, and spend model calls on *creating anchors* (re-ranking BM25 candidates by signatures, or hypothesising symbol names to resolve) before reading code.
4. **Order reading by cost, not only by rank:** small structural hits first, large symbols last, within an explicit token budget.

## 6. Related work
SWE-bench (Jimenez et al., 2024) introduced repository-level issue resolution and BM25 retrieval baselines; SWE-agent (Yang et al., 2024) showed that agent–computer interfaces drive performance. Agentless (Xia et al., 2024) localizes hierarchically from files to functions; AutoCodeRover (Zhang et al., 2024) exposes AST-level search APIs; RepoGraph (Ouyang et al., 2025) and LocAgent (Chen et al., 2025) build repository graphs for localization. We complement them with a budget-aware, statistically controlled measurement of the exact signals this harness exposes. Reciprocal-rank fusion follows Cormack et al. (2009); BM25 follows Robertson and Zaragoza (2009).

## 7. Limitations
Four public repositories, dominated by fastapi and rich; the hidden set is private. Gold labels approximate edited regions and exclude module-level edits. Token costs approximate characters/4. No execution-derived signals (running tests, tracebacks) are measured. Model-in-the-loop results are reported separately.

## 8. Reproducibility
`scripts/fetch_data.sh` downloads the dev subset (competition data is never redistributed); `python -m locstudy all` recomputes every table, figure and number in this paper from `data/`, recording data hashes, code commit and parameters in `results/summary.json`; `pytest` runs the unit tests on synthetic fixtures.

## References
Cormack, G. V., Clarke, C. L. A., Büttcher, S. (2009). Reciprocal rank fusion outperforms Condorcet and individual rank learning methods. SIGIR.
Chen, Z., et al. (2025). LocAgent: Graph-guided LLM agents for code localization. ACL.
Holm, S. (1979). A simple sequentially rejective multiple test procedure. Scandinavian Journal of Statistics.
Jimenez, C. E., et al. (2024). SWE-bench: Can language models resolve real-world GitHub issues? ICLR.
McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. Psychometrika.
Ouyang, S., et al. (2025). RepoGraph: Enhancing AI software engineering with repository-level code graph. ICLR.
Robertson, S., Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in IR.
Xia, C. S., Deng, Y., Dunn, S., Zhang, L. (2024). Agentless: Demystifying LLM-based software engineering agents. arXiv:2407.01489.
Yang, J., et al. (2024). SWE-agent: Agent-computer interfaces enable automated software engineering. NeurIPS.
Zhang, Y., Ruan, H., Fan, Z., Roychoudhury, A. (2024). AutoCodeRover: Autonomous program improvement. ISSTA.
