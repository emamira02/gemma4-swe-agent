<!-- AUTO-GENERATED from PAPER.template.md + results/*.json -->
# Anchors Decide: Measuring Code-Intelligence Signals for Issue Localization in Offline SWE Agents

*Gemma 4 Developer Agent — paper track. Every number is filled from `results/*.json` and every directional claim is checked against them at build time.*

## Abstract
An offline 31B agent with roughly six minutes per issue must find *where* to edit before it can edit. We measure how well the harness' code-intelligence signals — identifier resolution, call-graph expansion, pre-computed embedding neighbours — and plain BM25 recover the symbols that reference fixes actually change, on the 129 public development tasks, without and with Gemma 4 31B in the loop. Labels come from patches by an audited rule; estimates carry task-level bootstrap intervals and paired tests are multiplicity-corrected. Four findings shape agent design. (1) **Anchors decide:** when the issue names a resolvable symbol (58 tasks), reciprocal-rank fusion puts an edited symbol in the top 5 for 53.4% [41.4, 65.5] of tasks; when it names none (56 tasks) every structure-based signal collapses and only deep lexical search remains useful. (2) **Fusion must be mode-dependent:** without anchors, BM25 alone finds an edited symbol in the top 50 for 55.4% [42.9, 67.9] of tasks versus 28.6% [17.9, 41.1] for fusion (paired, post hoc; Holm p < 0.001). (3) **A reading budget erases fusion's advantage:** within 8k tokens of reading, fusion and BM25 are statistically indistinguishable. (4) **The model is most useful as a re-ranker:** letting Gemma 4 re-order BM25's top 50 by signatures lifts top-5 recall on anchor-free issues from 8.9% to 46.4% (pre-specified; Holm p < 0.001) at a median 17.12 s of model time per task, and a pre-specified two-mode policy beats both baselines over all tasks. Post hoc, re-ranking also beats fusion on anchored issues, and the bottleneck moves from ranking to candidate generation.

## 1. Introduction
The Gemma 4 Developer Agent harness offers three code-intelligence tools — `search_similar_code` over pre-computed node embeddings, `get_code_neighbors` and `get_code_subgraph` over a call graph — alongside shell and file tools, under tight budgets (≈ 6 min per hidden task, 32k-token context). `search_similar_code` resolves its query against **symbol names**, not free text: the tools are only as good as the anchors an agent can give them.

We ask: *given only the issue text, how often does each signal surface a symbol that the reference fix edits, at what reading cost, and how should signals be combined?* We contribute:
1. a reproducible labelling protocol mapping reference patches onto the harness' graph nodes, with a quantified label-quality audit;
2. a symbol- and file-level measurement of identifier, lexical, embedding and graph signals with bootstrap intervals and Holm-corrected paired tests;
3. a **reading-budget metric** (tokens read until the first edited symbol);
4. design rules for a two-mode localization policy, released as code;
5. a pre-specified evaluation of three ways to put the competition model in the loop, with their cost;
6. a single agent built on these rules, with dev-panel traces and leaderboard status.

## 2. Setting and data
The dev set has 129 tasks from fastapi, rich, requests and httpx; 126 change non-test, non-documentation source. Each commit ships a call graph (nodes are fully qualified symbols with source text; edges are `calls`) and 256-d node embeddings. The hidden test set (≈ 120 tasks) comes from private repositories, so we favour conclusions about *signal types* over repository-specific tuning.

## 3. Method
**Gold symbols.** For each hunk in a source file of the reference patch, the gold symbol is the most specific node containing at least half of the hunk's removed lines, ignoring imports and comments (pure additions: ≥ 2 context lines). The 50 % threshold was fixed before analysis. 425 of 660 hunks map to a node; the rest are module-level edits — imports or comments (62), module-level code outside any symbol (57) and additions of new module-level code, imports or definitions — which no symbol-level signal can point to. 114 tasks have at least one gold symbol.

**Label audit.** For 267 of 290 mapped edit hunks, *all* removed lines lie inside the chosen symbol. We also compared labels with the enclosing name in git's `@@` hunk header: they agree on 262 of 419 hunks, but 154 of the disagreements are git's funcname heuristic naming the *preceding* top-level definition (sometimes a code example inside a docstring), not label errors (confirmed on seeded samples). Coverage is therefore our primary label-quality measure.

**Signals (issue text only).** *Identifiers*: back-ticked names, dotted names, CamelCase, snake_case and calls, resolved like the harness (exact → dotted suffix → case-insensitive → substring) and ranked by match tier and specificity; *Identifiers+* adds traceback frames, imports and calls from code blocks. *BM25* indexes node-id tokens (double weight) and source. *Embedding neighbours* and *graph expansion* (1 or 2 hops) start from the top-3 anchors (identifiers, else BM25). *RRF* and *RRF+* fuse the lists by reciprocal rank (k = 60).

**Metrics.** Recall@k is the share of tasks with an edited symbol among the first k; MRR uses the first such rank. File-level variants count any symbol of an edited file. **Reading budget**: tokens (≈ characters/4) of full source an agent reads walking the ranking until the first edited symbol; we report Hit@{2k, 8k, 32k} and the median.

**Inference.** 95 % percentile intervals from 10,000 task-level bootstrap resamples (seed 0); paired comparisons use exact McNemar tests with Holm correction within each family, plus paired-bootstrap intervals for the difference. Fixed in advance: the primary method (RRF+), its comparison with every other signal at top-5 and top-20, and all parameters (k = 60, three anchors, BM25 k1 = 1.2, b = 0.75, 50 % label coverage), which a sensitivity analysis varies one at a time. The reading-budget and anchor-free comparisons were added after inspecting descriptive results and are marked *post hoc*.

## 4. Results
**4.1 Overall.** Across 114 tasks, RRF+ ranks an edited symbol in the top 5 for 32.5% [23.7, 41.2] of tasks and in the top 20 for 44.7% [36.0, 53.5]. BM25 is the best single signal in depth (top 50: 68.4% [59.7, 77.2]); graph expansion and RRF share the highest top-1 rate (16.7% [9.7, 23.7] and 16.7% [9.7, 23.7]). At file level, one-hop graph expansion finds an edited file in the top 5 for 50.8% [42.1, 59.5] (Tables 1–3 in RESULTS.md).

**4.2 Anchors decide.** 65 of 126 source-changing issues name a symbol that resolves in the graph. With such an anchor, RRF+ reaches 53.4% [41.4, 65.5] at top-5 and 72.4% [60.3, 82.8] at top-20. Without one, RRF+ falls to 10.7% [3.6, 19.6] at top-5; embedding neighbours (7.1% [1.8, 14.3]) and one-hop graph expansion (8.9% [1.8, 17.9]) stay low even at top-50: in this mode their anchors are BM25's top results, and BM25's own top-5 contains an edited symbol for only 8.9% [1.8, 17.9] of these tasks (Figure 1). Richer extraction from tracebacks and code blocks did not create new anchors on these issues: Identifiers+ matches Identifiers.

**4.3 Fusion must be mode-dependent (post hoc).** In the anchor-free subset, BM25 alone recovers an edited symbol within the top 50 for 55.4% [42.9, 67.9] of tasks, whereas RRF+ reaches only 28.6% [17.9, 41.1] — a paired difference of +26.8 pp (95 % CI +14.2 pp to +41.1 pp; Holm p < 0.001).

**4.4 A reading budget erases fusion's advantage (post hoc).** Within 8k tokens of reading, BM25 reaches an edited symbol for 50.9% [42.1, 59.7] of tasks, RRF+ for 45.6% [36.8, 54.4] and RRF for 41.2% [32.5, 50.0]; the paired difference RRF+ − BM25 is -5.3 pp (95 % CI -14.0 pp to +3.5 pp; Holm p = 0.534). Fusion's hits also arrive later: median reading cost to the first edited symbol is 6,464 tokens for RRF+, 4,991 for BM25 and 646 for graph expansion when it succeeds (Figure 3).

**4.5 How confident are the differences?** RRF+ significantly beats identifiers, embedding neighbours and one-hop graph expansion at top-20 (Holm p < 0.001 vs graph). Its advantage over BM25 at top-5 — +7.0 pp (95 % CI -1.8 pp to +15.8 pp; Holm p = 0.303) — is **not** statistically reliable at this sample size. Without a model, we therefore claim mode dependence and budget effects, not a universal winner.

**4.6 Graph distance.** From the nearest anchor, the edited symbol is the anchor itself in 28 tasks, 1 hop away in 8, 2 in 18, 3 in 12, 4 in 21 and unreachable within 4 hops in 27 (Figure 2). The `calls`-only graph is sparse: expansion beyond one hop must be budgeted, not exhaustive.

**4.7 Robustness.** Every one-at-a-time variant of the fixed parameters (RRF k, anchor count, BM25 parameters, label strictness) leaves RRF+ top-5 recall inside the main estimate's 95 % interval; a single anchor instead of three gives the lowest value, 27.2%. Per-repository results differ (RESULTS.md): repository style matters, so we prefer mode rules over tuned weights.

**4.8 Without graph or embeddings (post hoc).** An agent's task container has neither the call graph nor the embeddings, so a localization step that runs there can use only identifiers and BM25. Applying the mode rule of 4.3 to them (fuse identifiers with BM25 when they resolve, BM25 alone otherwise) gives a lexical policy that places an edited symbol in the top 5 for 34.2% [25.4, 43.0] of tasks: level with RRF+ (+1.8 pp; Holm p = 0.774) and ahead of BM25 (+8.8 pp, 95 % CI +2.6 pp to +14.9 pp; Holm p = 0.026). In the top 50 it reaches 70.2% [61.4, 78.1] versus 55.3% [46.5, 64.0] for RRF+ (+14.9 pp, 95 % CI +6.1 pp to +23.7 pp; Holm p = 0.003): with no weak anchors to dilute it, deep lexical recall is kept. Our agent's localization skill implements this policy. For a model that re-ranks a candidate pool (4.9), it is the better pool.


**4.9 Model in the loop.** We repeated the measurement with the competition model (Gemma 4 31B QAT on 4× L4 with vLLM, temperature 0, thinking disabled, prompts hashed `1737974fa6ea3223`) on 114 of 114 tasks, under the same labels and parameters. Three uses were compared: *hypotheses* (the model names likely symbols from the issue and a module list; names are resolved like identifiers), *hypotheses + fusion* (hypotheses fused with the other signals by RRF), and *re-rank* (the model re-orders BM25's top 50, shown as id and signature line, and its list is followed by the rest of BM25). The *two-mode policy* uses RRF+ when the issue names a resolvable symbol and the re-rank otherwise. Hypotheses H1–H3 and the analysis code were committed before the model outputs were downloaded (commit `136a864`). Valid JSON: 100.0% of hypothesis and 100.0% of re-rank prompts; a hypothesised symbol resolved for 86.8% of tasks.

**Creating anchors (H2, anchor-free issues).** Re-ranking BM25's top 50 raises top-5 recall from 8.9% [1.8, 17.9] to 46.4% [33.9, 58.9]: a paired difference of +37.5 pp (95 % CI +25.0 pp to +50.0 pp; Holm p < 0.001); only the re-rank succeeded on 21 tasks, only BM25 on 0. At top-20 the gain is +26.8 pp (Holm p < 0.001). Hypotheses + fusion reach 23.2% [12.5, 35.7] (+14.3 pp vs BM25, 95 % CI +1.8 pp to +26.8 pp): the bootstrap interval excludes zero but the pre-specified McNemar test does not (Holm p = 0.057), so H2 is supported for re-ranking only.

**The two-mode policy (H1) and hypothesis fusion (H3).** Over all tasks the policy reaches top-5 recall 50.0% [41.2, 58.8], versus 32.5% [23.7, 41.2] for RRF+ (+17.5 pp, 95 % CI +10.5 pp to +24.6 pp; Holm p < 0.001) and 25.4% [17.5, 33.3] for BM25 (+24.6 pp; Holm p < 0.001); both gains hold at top-20 (Holm p < 0.001 vs RRF+, < 0.001 vs BM25). Hypotheses + fusion do not reliably beat RRF+ over all tasks (+7.9 pp, 95 % CI -0.9 pp to +16.7 pp; Holm p = 0.122).

**Post hoc: re-rank in both modes.** The policy's anchored branch was the weak one. On issues that name a symbol, the re-rank reaches top-5 recall 75.9% [65.5, 86.2] versus 53.4% [39.7, 65.5] for RRF+ (+22.4 pp, 95 % CI +8.6 pp to +36.2 pp; Holm p = 0.009 across three exploratory tests), so re-ranking everywhere would beat the pre-specified policy by +11.4 pp over all tasks. Within an 8k-token reading budget the re-rank reaches 64.0% [55.3, 72.8] versus 50.9% [41.2, 60.5] for BM25 (Holm p < 0.001). These post hoc comparisons need confirmation on new tasks (Figure 4).

**Ceiling and cost (post hoc).** A re-ranker cannot recover what its pool misses: BM25's top 50 contains an edited symbol for 68.4% [59.7, 77.2] of tasks (55.4% [42.9, 67.9] without anchors), and on those tasks the re-rank puts one in the top 5 for 89.7% [82.0, 96.2]. Ranking is no longer the bottleneck; candidate generation is. Adding the hypothesis-fused top 50 to the pool would raise reachability to 79.0% [71.0, 86.0] (BM25's top 100: 73.7% [65.8, 81.6]); the re-ranker is untested on such pools. Median model time was 17.12 s per task (p90 28.07 s; both calls, measured under concurrent batching) and ≈ 3,682 tokens: under 5 % of the ≈ 6-minute per-task budget. Full tables: RESULTS_LLM.md.



**4.10 The agent.** Our submission is a single agent built on 4.8. A skill script runs the graph-free lexical policy inside the task container and prints the top symbols with file ranges and signatures; the model re-ranks them, reads one to three ranges and edits; a second script reverts test edits and compiles changed files before `submit_patch`. We run each configuration on a development panel of 24 rich tasks with the scorer's settings mirrored on 4× L4 (5.0-minute sessions); the reference patch passes the tests on 21 of them in this environment. The first configuration, S1, resolved 4 of these 21 (19.0%). Its traces show where the loop fails: more sessions hit the time limit (16) than were resolved, 14 tasks contained malformed tool calls (48 of 602 calls wrapped arguments in backticks) and 5 never edited a file; later tags target these failures. The panel is small, single-repository and run once: a debugging instrument, not an estimate of hidden-set performance. No public leaderboard score had been returned when this paper was built; the table shows each configuration's status.


| Tag | Panel tasks (solvable) | Resolved | Timeouts | Tasks with malformed calls | Median s to first edit | Public score |
|---|---|---|---|---|---|---|
| S1 | 24 (21) | 4 | 16 | 14 | 95 | pending |


## 5. Implications for agent design
1. **Detect the mode first.** Resolve identifiers from the issue in one cheap step: whether any resolve sets the localization mode.
2. **Let the model re-rank, in both modes.** Show it the issue and the id and signature line of about 50 candidates and read its top 5 first; one call costs a few percent of the per-task budget. The evidence is pre-specified for anchor-free issues and post hoc for anchored ones.
3. **Build the pool for recall.** The re-ranker cannot recover what the pool misses: start from the graph-free lexical policy (4.8), which keeps BM25's depth and adds resolved identifiers, and add hypothesis-fused candidates before re-ranking.
4. **Keep a model-free fallback.** If the call fails or times out, use RRF+ when anchors exist and plain BM25 otherwise; never fuse structure-based lists without anchors.
5. **Order reading by cost, not only by rank:** small structural hits first, large symbols last, within an explicit token budget.

## 6. Related work
SWE-bench (Jimenez et al., 2024) introduced repository-level issue resolution with BM25 baselines; SWE-agent (Yang et al., 2024) showed that agent–computer interfaces matter. Agentless (Xia et al., 2024) localizes hierarchically from files to functions; AutoCodeRover (Zhang et al., 2024) exposes AST-level search APIs; RepoGraph (Ouyang et al., 2025) and LocAgent (Chen et al., 2025) build repository graphs for localization. We add a budget-aware, statistically controlled measurement of the signals this harness exposes and of the competition model's role in combining them. Reciprocal-rank fusion follows Cormack et al. (2009); BM25 follows Robertson and Zaragoza (2009).

## 7. Limitations
Four public repositories, dominated by fastapi and rich; the hidden set is private. Labels exclude module-level edits. Token costs approximate characters/4. No execution-derived signals (running tests, tracebacks) are measured. The model results come from one prompt pair and one greedy run; batched inference is not bit-reproducible, so the analysis re-runs from saved outputs. The four repositories are popular open-source projects that the model has likely seen in pre-training; hypotheses could draw on memorised code, which would not transfer to the private hidden set. The re-ranker sees only issue text, names and signatures, which limits but does not exclude this effect.

## 8. Reproducibility
`scripts/fetch_data.sh` downloads the dev subset (competition data is never redistributed); `python -m locstudy all` recomputes every table, figure and number in this paper from `data/`, recording data hashes, code commit and parameters in `results/summary.json`; the Kaggle kernel `kernels/llm-localization` (built by `kernels/build_v2.py` from the same code) produces the model outputs and `python -m locstudy llm` analyses them. The build fails if any machine-checked claim contradicts the results; `pytest` runs unit tests on synthetic fixtures.

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
