<!-- AUTO-GENERATED from PAPER.template.md + results/*.json -->
# Anchored or Not: Localization and Re-ranking in an Offline Gemma 4 Agent

*Issue anchors predict localization; model re-ranking recovers anchor-free issues; losses come after localization.*

## Abstract
An offline agent must find *where* to edit before it can edit. On the 114 public development tasks of the Gemma 4 Developer Agent competition that have symbol labels derived from reference patches, we measure how often the harness' code-intelligence signals (identifier resolution, call-graph expansion, embedding neighbours), BM25 and Gemma 4 31B as an untuned re-ranker put an edited symbol in the top 5 (Hit@5), and what limits the agent built on them. (1) **Anchors predict difficulty for every signal.** Issues that name a resolvable symbol (58) reach Hit@5 53.4% with reciprocal-rank fusion, the other 56 only 10.7%; deeper in the ranking, BM25 finds far more for them than fusion or structure-based signals. (2) **The re-ranker recovers anchor-free issues** (Hit@5 8.9% → 46.4%, pre-specified; Holm p < 0.001) for a median 17.12 s of batched model time per task, but the anchor gap stays about as large as under BM25, and post hoc, anchors still predict success after controlling for issue–code lexical overlap. (3) **The agent loses issues after localization:** of 85 unresolved runs, 10 edited only wrong files, and 30 of the 35 that never edited had read a file the fix edits. A serialization failure, diagnosed in all 77 malformed two-argument edit calls, touches 9 of the unresolved runs. Four repositories and one model bound these conclusions.

## 1. Introduction
The Gemma 4 Developer Agent harness offers three code-intelligence tools — `search_similar_code` over pre-computed node embeddings, `get_code_neighbors` and `get_code_subgraph` over a call graph — alongside shell and file tools, under tight budgets (≈ 6 min per hidden task, 32k-token context). `search_similar_code` resolves its query against **symbol names**, not free text: the tools are only as good as the anchors an agent can give them.

We contribute:
1. a symbol-level measurement of identifier, lexical, embedding, graph and model re-rank signals, split by whether the issue names a resolvable symbol, with pre-specified model hypotheses;
2. a failure decomposition of the agent's development runs, with a per-call diagnosis of a tool-serialization failure.

## 2. Setting and data
The dev set has 129 tasks from fastapi, rich, requests and httpx; 126 change non-test, non-documentation source. Each commit ships a call graph (nodes are fully qualified symbols with source text; edges are `calls`) and 256-d node embeddings. The hidden test set (≈ 120 tasks) comes from private repositories, so we favour conclusions about *signal types* over repository-specific tuning.

## 3. Method
**Gold symbols.** For each hunk in a source file of the reference patch, the gold symbol is the node whose source contains most of the hunk's removed lines (at least half, matched as stripped text, ignoring imports and comments; pure additions: ≥ 2 context lines). 425 of 660 hunks map; the rest are module-level — imports or comments (62), code outside any symbol (57), new module-level code or definitions — or lines that matched no node (16). 114 tasks have at least one gold symbol. The labels are rule-based: for 267 of 290 mapped edit hunks every removed line occurs in the chosen symbol (the same text test at 100 %), and git's `@@` hunk-header name, an independent check, agrees on 262 of 419 (154 disagreements are git naming the *preceding* definition).

**Signals (issue text only).** *Identifiers*: back-ticked names, dotted names, CamelCase, snake_case and calls, resolved like the harness (exact → dotted suffix → case-insensitive → substring); *Identifiers+* adds traceback frames, imports and calls from code blocks. An issue is *anchored* when an Identifiers+ name resolves; otherwise BM25's top 3 serve as anchors. *BM25* indexes node-id tokens (double weight) and source. *Embedding neighbours* and *graph expansion* (1 or 2 hops) start from three anchors. *RRF* fuses identifiers, BM25, embedding neighbours and one-hop expansion by reciprocal rank (k = 60); *RRF+* fuses Identifiers+, BM25, embedding neighbours of its anchors and two-hop expansion.

**Model.** Gemma 4 31B QAT (4× L4, vLLM, temperature 0, thinking off, prompts hashed `1737974fa6ea3223`) ran on all 114 tasks: *hypotheses* (symbols it names from the issue and a module list), *hypotheses + fusion* (added to RRF), and *re-rank* (it picks the 10 most likely of BM25's top 50, each shown by id, signature and first docstring line, and these lead BM25's order). The *two-mode policy* uses RRF+ when anchored and the re-rank otherwise. Pre-specified before the model outputs existed (commit `6a28d29`): H1, the policy beats RRF+ and BM25 overall; H2, on anchor-free issues the re-rank and hypotheses + fusion beat BM25; H3, hypotheses + fusion beat RRF+ overall.

**Metrics and inference.** Hit@k is the share of tasks with at least one edited symbol among the first k (Recall@k in earlier drafts). The *reading budget* counts tokens of source (characters/4) read down the ranking until the first edited symbol, like the EXAM effort score (Wong et al., 2016). Intervals are 95 % percentiles of 10,000 task-level bootstrap resamples (seed 0); paired comparisons use exact McNemar tests with Holm correction per family. Parameters are common defaults (k = 60, three anchors, BM25 k1 = 1.2, b = 0.75), but an exploratory pass on the same tasks preceded the declared comparison family (RRF+ against every signal at top-5 and top-20) and the 50 % label rule: only H1–H3 are strictly pre-specified, and later comparisons are marked *post hoc*.

## 4. Results
**4.1 Overall (declared comparisons).** Across 114 tasks, RRF+ reaches Hit@5 32.5% [23.7, 41.2] and Hit@20 44.7% [36.0, 53.5]; BM25 is the best single signal in depth (Hit@50 68.4% [59.7, 77.2]), and one-hop expansion finds an edited *file* in the top 5 for 50.8% [42.1, 59.5] of 126 source-changing tasks. RRF+ beats identifiers and embedding neighbours at top-5 and top-20 and one-hop expansion at top-20 (Holm p < 0.001 for the latter), but not two-hop expansion, RRF or BM25 at either depth; its top-5 advantage over BM25 is +7.0 pp (95 % CI -1.8 pp to +15.8 pp; Holm p = 0.303). Full family: [RESULTS.md](https://github.com/emamira02/gemma4-swe-agent/blob/main/paper/RESULTS.md).

**4.2 Anchors.** 65 of 126 source-changing issues are anchored (58 of the 114 with gold symbols). Anchored issues are easier for every signal, BM25 included: Hit@5 41.4% versus 8.9% for BM25 and 53.4% versus 10.7% for RRF+ (Figure 1). Deeper down they part: without anchors, embedding neighbours (7.1% [1.8, 14.3]) and one-hop expansion (8.9% [1.8, 17.9]) stay low even at top-50, because their anchors are then BM25's top results, while BM25 itself reaches 55.4%. The edited symbol is the nearest anchor itself in 28 tasks and 1, 2, 3 or 4 call-graph hops away in 8, 18, 12 and 21; 27 are farther or unreachable (Figure 2).

![Figure 1](figures/fig1_recall_by_anchor.png)
*Figure 1. Hit@k by anchor stratum; bands: 95 % intervals.*

![Figure 2](figures/fig2_hop_distance.png)
*Figure 2. Call-graph hops from the nearest anchor to the edited symbol.*

**4.3 Without anchors, fusion dilutes BM25 in depth (post hoc).** Without anchors, BM25 alone recovers an edited symbol within the top 50 for 55.4% [42.9, 67.9] of tasks, RRF+ for only 28.6% [17.9, 41.1]: a paired difference of +26.8 pp (95 % CI +14.2 pp to +41.1 pp; Holm p < 0.001); at top-20 it is +7.1 pp (Holm p = 0.219). Within 8k tokens of reading, BM25 and RRF+ reach an edited symbol for 50.9% [42.1, 59.7] and 45.6% [36.8, 54.4] of all tasks (Holm p = 0.534; Figure 3).

![Figure 3](figures/fig3_reading_budget.png)
*Figure 3. Tasks whose first edited symbol is reached within N tokens of reading.*

**4.4 Robustness (declared parameters).** One-at-a-time variants of RRF k, anchor count and BM25 parameters keep RRF+ Hit@5 inside the main interval, but the main setting is the highest on all three axes (lowest variant: one anchor, 27.2%), so its estimate is optimistic.

**4.5 Without graph or embeddings (post hoc).** Task containers lack the graph and embeddings. Fusing traceback frames and identifiers with BM25 when they resolve, and BM25 alone otherwise, gives a lexical policy with Hit@5 34.2% [25.4, 43.0]: +1.8 pp versus RRF+ (95 % CI -4.4 pp to +7.9 pp) and +8.8 pp versus BM25 (Holm p = 0.026); at top-50, 70.2% [61.4, 78.1] versus 55.3% [46.5, 64.0] for RRF+ (Holm p = 0.003). Our agent's localization skill implements this policy.

**4.6 Model in the loop: creating anchors (H2).** On anchor-free issues the re-rank raises Hit@5 from 8.9% [1.8, 17.9] to 46.4% [33.9, 58.9]: +37.5 pp (95 % CI +25.0 pp to +50.0 pp; Holm p < 0.001); only the re-rank succeeded on 21 tasks, only BM25 on 0, and the gain at top-20 is +26.8 pp (Holm p < 0.001). Hypotheses + fusion reach 23.2% [12.5, 35.7]; the bootstrap interval of their gain excludes zero but the pre-specified McNemar test does not (Holm p = 0.057), so H2 holds for re-ranking only. The server enforced valid JSON.

**The policy (H1) and hypothesis fusion (H3).** Over all tasks the policy reaches Hit@5 50.0% [41.2, 58.8], versus 32.5% for RRF+ (Holm p < 0.001) and 25.4% for BM25 (Holm p < 0.001), also at top-20; as the policy is RRF+ on anchored issues, H1 restates H2's anchor-free gain. Hypotheses + fusion do not reliably beat RRF+ (+7.9 pp; Holm p = 0.122).

**Post hoc: re-rank in both modes, and its ceiling.** On anchored issues the re-rank reaches Hit@5 75.9% [65.5, 86.2] versus 53.4% for RRF+ (Holm p = 0.009; this test and re-rank versus the policy share their discordant tasks). A re-ranker cannot recover what its pool misses: BM25's top 50 holds an edited symbol for 68.4% [59.7, 77.2] of tasks, and on those the re-rank puts one in the top 5 for 89.7% [82.0, 96.2] (Figure 4). Model time per task, for both calls under concurrent batching, had median 17.12 s (p90 28.07 s) and a mean of 3,683 tokens.

![Figure 4](figures/fig4_model_in_loop.png)
*Figure 4. Hit@5 with and without the model, by anchor stratum; bars: 95 % intervals.*

**Why the anchor gap persists (post hoc; plan committed in `cd93427` before the analysis code, with the first two point estimates already known).** The anchor gap in Hit@5 is +29.4 pp [+11.9, +46.9] for the re-rank, +32.5 pp [+18.2, +46.4] for BM25 and +42.7 pp [+27.0, +58.2] for RRF+ (stratified resampling); the re-rank's gap differs from BM25's by +3.0 pp [-14.8, +22.0] and from RRF+'s by +13.3 pp [-5.8, +32.3], so it is not shown to be narrower. Writing Hit@5 as reachability (BM25's top 50 holds an edited symbol: 81.0% anchored, 55.4% anchor-free) times ranking given reachability (93.6%, 83.9%) attributes 77.4% [45.0, 115.6] of the re-rank's gap to reachability: by the registered criterion, an interval above 50 %, the split is not resolved. With issue–code lexical overlap in a logistic model, anchors still predict Hit@5 for BM25, RRF+ and the re-rank (odds ratio 4.31 [2.07, 10.60] for the re-rank; 55 and 28 resamples could not be fitted for BM25 and RRF+), and anchor-free issues overlap slightly more with the gold code. The gap also holds within fastapi and within rich (descriptive, not registered).

**4.7 The agent.** Our agent runs the lexical policy of 4.5 in the task container, lets the model pick among the printed symbols, reads one to three ranges, edits, and checks the patch before `submit_patch`. Configurations S1–S5 each ran once, with the scorer's settings, on the same 24 rich tasks; the reference patch passes on 107 of 120 task runs (21 or 22 per run: the environment is noisy). On 57.9% of these the policy ranks an edited file first, yet each configuration resolves only 4–5 tasks. Of 85 unresolved runs, 10 edited only files the fix leaves untouched, 40 edited one it touches but timed out (20) or submitted a wrong fix (20), and 35 never applied an edit, though 30 of these had read such a file (26 ranked first by the policy). 77 of 248 `edit_file` calls arrived with an argument missing, and all 77 show one mechanism: the published chat template lists tool parameters in sorted order, the model emits them so (170 of 171 well-formed calls), and vLLM's gemma4 parser ends a string only at a dedicated token, so `old_string` sits inside `new_string`, after the backtick (72) or quote (5) that closed it. `write_file`, whose `content` sorts before `filepath`, lost `filepath` the same way in 4 of 94 calls. These failures touch 9 of the unresolved runs. Later configurations pass code in one argument; the eras below also differ in prompt, budget, sampling and panel: system comparisons. Public leaderboard scores come from one scored run per configuration on the hidden tasks; differences between configurations are not tested.

| Edit channel | Tags | Panel | Resolved / solvable runs | Malformed calls (all tools) | Public score |
|---|---|---|---|---|---|
| edit_file (two code arguments) | S1–S5 | rich | 22/107 | 119/2,655 (4.5%) | S1 0.15, S3 0.12, S5 0.12 |
| heredoc editor (one argument) | S7, S8, S9, S12 | fastapi+rich; rich | 37/91 | 8/2,056 (0.4%) | S12 0.17 |
| public prompt, edit_file | B1 | rich | 6/21 | 61/625 (9.8%) | not submitted |

*Excluded: S6 (editor unreachable in 15 tasks); S13 (targeted panel).*

## 5. Implications for agent design
1. **Detect the mode first:** whether any identifier resolves predicts how hard localization will be; without anchors, structure-based tools are not worth their calls.
2. **Re-rank BM25's candidates with the model,** and spend further effort on the pool, which bounds the re-rank.
3. **Make a code-valued string the only or the last argument in sorted key order:** with this serving stack, a string the model closes with a backtick or quote swallows every later argument.

## 6. Related work
In IR-based bug localization, reports that name buggy files inflate accuracy (Kochhar et al., 2014), program-entity names largely decide whether developers are helped (Wang et al., 2015), and queries can be reformulated by report type (Rahman and Roy, 2018); we carry this distinction to an agent harness and a model re-ranker. SWE-bench (Jimenez et al., 2024) introduced repository-level issue resolution with BM25; SWE-agent (Yang et al., 2024) showed that the agent–computer interface matters, as our serialization failure confirms. Agentless (Xia et al., 2024) localizes hierarchically; RepoGraph (Ouyang et al., 2025) and LocAgent (Chen et al., 2025) build repository graphs, LocAgent relating success to graph distance from mentioned functions. Bellam (2026) stratifies SWE-bench Verified by hop depth and finds that small agents, Gemma 4 among them, use graph tools mostly for name lookup and one expansion; we add issues without resolvable names and a model re-ranker. SweRank (Reddy et al., 2026) fine-tunes a listwise re-ranker and finds retrieval not to be the bottleneck behind a trained retriever; behind BM25, with an untuned quantized model, the pool is. Caumartin et al. (2026) report large file-level gains from LLM re-ranking; Sam-Bodden (2026) fixes localization with an oracle to study acting. On these tasks, Hassan (2026) benchmarks model-free signals and Wold (2026) pre-registered a study of anchor distance and E4B failures; we add symbol labels, the model re-rank per stratum and the agent's losses. RRF follows Cormack et al. (2009); BM25, Robertson and Zaragoza (2009).

## 7. Limitations
Four public repositories, dominated by fastapi and rich, and one model: the hidden set is private, and these tasks informed every design choice, so post hoc results need new tasks. Labels come from a text-matching rule, exclude module-level edits and take the reference patch as the one correct fix. The model results come from one prompt pair and one greedy run; batched inference is not bit-reproducible, so the analysis re-runs from saved outputs. The model has likely seen these popular repositories in pre-training; the re-ranker sees only issue text, names, signatures and docstring lines, which limits but does not exclude memorisation. The agent decomposition covers five single runs on one rich panel.

## 8. Reproducibility
Code and result files: https://github.com/emamira02/gemma4-swe-agent. Competition data are never redistributed: `scripts/fetch_data.sh` downloads the dev subset, and `python -m locstudy all` recomputes every localization table and figure from `data/`, with data hashes, commit and parameters (a full rerun reproduced every value). Kaggle kernels produce the model outputs (`kernels/llm-localization`) and agent traces, which stay private as they contain task text; `locstudy llm`, `analysis.anchor_posthoc`, `analysis.failure_audit`, `tools/agent_summary.py` and `analysis.serialization_audit` derive the committed result files, which keep task ids and counts only. [`paper/CLAIMS.md`](https://github.com/emamira02/gemma4-swe-agent/blob/main/paper/CLAIMS.md) maps every number to its result key; the build fails if a guarded claim contradicts the results.

## References

Bellam, S. (2026). How do small coding agents use code graphs and embeddings? arXiv:2610.33958.

Caumartin, G., Chen, T.-H., Costa, D. E. (2026). Retrieval-oriented code representations in agentic bug localization. arXiv:2607.11046.

Chen, Z., et al. (2025). LocAgent: Graph-guided LLM agents for code localization. ACL.

Cormack, G. V., et al. (2009). Reciprocal rank fusion outperforms Condorcet and individual rank learning methods. SIGIR.

Hassan, A. (2026). Model-free localization benchmark on the 129 public tasks. Kaggle discussion 748395.

Holm, S. (1979). A simple sequentially rejective multiple test procedure. Scandinavian Journal of Statistics.

Jimenez, C. E., et al. (2024). SWE-bench: Can language models resolve real-world GitHub issues? ICLR.

Kochhar, P. S., Tian, Y., Lo, D. (2014). Potential biases in bug localization: Do they matter? ASE.

McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. Psychometrika.

Ouyang, S., et al. (2025). RepoGraph: Enhancing AI software engineering with repository-level code graph. ICLR.

Rahman, M. M., Roy, C. K. (2018). Improving IR-based bug localization with context-aware query reformulation. ESEC/FSE.

Reddy, R. G., et al. (2026). SweRank: Software issue localization with code ranking. ICLR.

Robertson, S., Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in IR.

Sam-Bodden, B. (2026). What context does a coding agent actually need to act? arXiv:2607.09691.

Wang, Q., Parnin, C., Orso, A. (2015). Evaluating the usefulness of IR-based fault localization techniques. ISSTA.

Wold, J. (2026). Pre-registration: anchor distance and small-agent failure. Kaggle discussion 750732.

Wong, W. E., et al. (2016). A survey on software fault localization. IEEE TSE.

Xia, C. S., et al. (2024). Agentless: Demystifying LLM-based software engineering agents. arXiv:2407.01489.

Yang, J., et al. (2024). SWE-agent: Agent-computer interfaces enable automated software engineering. NeurIPS.
