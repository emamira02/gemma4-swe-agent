# Post hoc anchor analyses (registered 2026-11-02, before computing them)

Status: exploratory, on the 114 development tasks already used for every decision in the paper. Registering the
analysis fixes its definitions and reading before the estimates exist; it does not make them confirmatory.
H1-H3 (commit 6a28d29) are unchanged.

Already seen before this note (results/llm_summary.json): Hit@5 per stratum for BM25, RRF+ and the re-rank, and
for the re-rank the share of tasks whose BM25 top-50 contains an edited symbol and Hit@5 given that it does. So
the point estimates of Q1 and Q2 are known; their intervals are not. Nothing of Q3 has been computed.

Population: tasks with at least one gold symbol (n = 114): anchored = the issue names a symbol that resolves in
the graph (58), anchor-free (56), as in the paper. Outcome: Hit@5 per task (any edited symbol in the top 5).
Methods: BM25, RRF+, re-rank of BM25's top 50 (results/kaggle_v2/llm_rows.jsonl).
Uncertainty: 10,000 bootstrap resamples, seed 0, tasks resampled within each stratum (stratum sizes fixed);
95 % percentile intervals. No p-values and no multiplicity claims: estimates with intervals only.

Q1. Does the re-rank change the anchor gap? gap(m) = Hit@5(anchored) - Hit@5(anchor-free) for method m;
report gap(m) and gap(baseline) - gap(re-rank) for baseline in {BM25, RRF+}. Reading: an interval that
includes 0 means no evidence that the re-rank narrows the gap relative to that baseline.

Q2. Where does the re-rank's remaining gap come from? Hit@5 = R x C, R = BM25 top-50 contains an edited symbol,
C = re-rank Hit@5 given R. Share of gap(re-rank) due to R = average of the two one-factor-at-a-time
counterfactuals (swap R first, or C first). Report the share and its interval. Reading: a share above 0.5 with
an interval above 0.5 means most of the remaining gap is candidate generation, not ranking.

Q3. Is anchor status more than lexical overlap? overlap = share of the issue's distinct terms (locstudy.signals.toks
on the problem statement) that occur in the ids or source of the task's gold symbols (retrospective: it uses the
gold labels). Per method: logistic regression Hit@5 ~ anchored + standardised overlap; report the odds ratio of
anchored with its interval (resamples where a coefficient cannot be estimated are counted and reported), and the
mean overlap per stratum. Reading: for a method, an odds-ratio interval above 1 means anchor status predicts
Hit@5 beyond this overlap measure; an interval that includes 1 means the anchor effect is not distinguishable
from it. A significant result for one method and not another is not by itself a difference between methods.

Output: results/anchor_posthoc.json via python -m analysis.anchor_posthoc (aggregates only, no task text).
The paper may report these only as post hoc, with their intervals, whatever they show.

## Addendum 2026-11-02 22:24 UTC (after computing Q1-Q3; not registered)
Q3's model does not control for repository, and anchor status differs by repository. Added one descriptive check
only, chosen after seeing Q1-Q3: Hit@5 counts per repository and anchor stratum for the three methods
(results/anchor_posthoc.json, by_repo_hit5_unregistered). No other variant was computed.

Correction 2026-11-02 22:53 UTC: the addendum heading first said ~22:40 UTC, an estimate written without a clock.
The record is the git history: this note was committed in cd93427 at 22:22:04 UTC, before the analysis code
existed; the code, its results and the addendum followed in 55ac7a9 at 22:24:59 UTC.
