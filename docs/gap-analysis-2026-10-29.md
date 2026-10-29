# Gap analysis: current position to the medal zone (2026-10-29)

Read-only analysis. Nothing was submitted and nothing was changed in `submit_queue.json`, `agent/`, `candidates/`
or the scheduled tasks. Sources were read on 2026-10-29 between ~11:25 and ~12:40 UTC: the Kaggle leaderboard
(CLI download), the competition Overview/Rules/Data pages, the Kaggle progression page, 24 public notebooks
(pulled with `kaggle kernels pull`, read but never executed) and ~20 forum threads. Third-party numbers are
labelled as such; most are single runs that I could not reproduce.

## 0. Bottom line

- Today the user is rank 1,564 of 4,100 at 0.17 (10/58). A medal on the current public board needs 12/58
  (0.20, ranks 58-289); 11/58 is not enough for a new submission because ties go to the earlier submission and
  the 11/58 band already spans ranks 290-881.
- Our best configuration (S12 family) is the public V10/Budget-Fit family: same `eval_config` (240 s / 28 calls /
  8 min / 80 turns, byte-identical in all 10 public bundles checked) and the same sampling (T 0.2). That family
  averages ~10/58 over 10 public draws. **Our true mean is the field's median-config mean, ~10/58.**
- A medal on the private board most likely needs a true mean of ~11.5-12/58 (section 1.4): **+1.5 to +2 tasks of
  mean, about +15-20% relative.** No public configuration has demonstrated a reproducible gain of that size. The
  only large measured effects in public evidence are losses (no thinking, fewer calls, shorter caps, smaller
  models, multi-agent designs).
- So the plan is two-pronged: (a) take the few levers with real evidence or real mechanism (sampling, final
  selection/timing, call cap), validated on a better panel; (b) play the private-board structure correctly
  (tie-break timing, two decorrelated finals). Honest estimate: with the current mean, a medal is roughly a
  coin flip at best and depends on luck and tie-breaks; the levers below raise those odds, none guarantees it.

Top 3 actions: section 4, items P1-P3.

## 1. Leaderboard structure (verified)

### 1.1 Medal rule and eligibility
- Kaggle progression page (read today): for 1000+ teams, **bronze top 10%, silver top 5%, gold top 10 + 0.2%**,
  percentages rounded down. With 4,100 teams: bronze rank <= 410, silver <= 205, gold <= 18. Team count can still
  grow until the entry deadline (25 Nov), so the cutoffs can still move up.
- Overview page: the competition "Awards Points & Medals" (4,100 teams, 27,187 submissions).
- Rules: "In the event of a tie, the Submission that was entered first to the Competition will be the winner."

### 1.2 Score granularity
Public score = solved/58, truncated to 2 decimals (only 14 distinct values exist; confirmed by forum 753524):
0.17 = 10, 0.18 = 11, 0.20 = 12, 0.22 = 13, 0.24 = 14. Data page: ~120 test tasks "evenly divided between the
public and private splits", curated from private repositories, and every test task was checked to be passable (or
within one test) by a larger frontier model.

### 1.3 Public board, 2026-10-29 11:25 UTC (4,100 teams)

| Score | Tasks | Teams | Ranks | Median submissions per team |
|---|---|---|---|---|
| 0.24 | 14 | 6 | 1-6 | 12 |
| 0.22 | 13 | 51 | 7-57 | 16 |
| 0.20 | 12 | 232 | 58-289 | 12 |
| 0.18 | 11 | 592 | 290-881 | 10 |
| 0.17 | 10 | 704 | 882-1585 | 7 |
| 0.15 | 9 | 591 | 1586-2176 | 5 |

- Cutoffs today: gold (18) inside the 13/58 band, silver (205) inside the 12/58 band, bronze (410) inside the 11/58
  band. A new submission lands at the end of its band, so from the user's 10/58: bronze needs 12/58 (+2 tasks),
  silver 13/58 (+3), gold 14/58 (+4).
- The top bands are dominated by teams with many submissions: the public board keeps each team's best draw, so the
  0.22-0.24 scores are mostly high draws of ~10-11/58 configurations (Budget-Aware v2 identical files drew 7, 7, 9,
  11, 13; Budget-Fit 8-11 over 10 draws, mean 10.0; same zip 0.13 and 0.17 for victorzhong; Sahil Das 0.17, 0.15,
  0.13, 0.15). Repeated-draw SD per run: ~1.5-2.2 tasks (pooled from the public draws; Adam Johnson in 753524
  measures ~2 on a 58-task draw; binomial upper bound 2.9).

### 1.4 What the private board probably needs (model, not measurement)
The private score of a team is the better of its two selected submissions on the other ~58 tasks. Best-of-many
inflation disappears, so private scores regress toward the configurations' true means; many teams will
auto-select or hand-pick their luckiest public draws. Consequences:
- The private bronze cutoff is probably near 11 or 12 tasks, inside a band of several hundred teams where order is
  decided by submission time. A late submission sits at the end of its band.
- Probability that the better of two independent draws reaches k tasks (binomial on 58 / normal with SD 2):

| True mean | P(best of 2 >= 11) | >= 12 | >= 13 |
|---|---|---|---|
| 10 | 0.66 / 0.64 | 0.50 / 0.40 | 0.34 / 0.20 |
| 11 | 0.80 / 0.84 | 0.66 / 0.64 | 0.51 / 0.40 |
| 12 | 0.90 / 0.95 | 0.80 / 0.84 | 0.67 / 0.64 |

  Caveat: two near-identical configurations are correlated on the same private tasks, so the real best-of-2 gain
  is smaller than the table shows unless the two finals differ. With the mean below the cutoff, more variance and
  less correlation between the two finals raise the odds (section 4, P2).

## 2. What the field does (24 notebooks + forum)

Full per-notebook notes (kept outside the repo): side-session notes `notebooks-A.md`, `notebooks-B.md`.

### 2.1 Facts
- **Architecture is converged.** Every scored 31B bundle in these notebooks is one `LlmAgent` with no sub-agents,
  best-of-n, candidate selection, critic or retry logic; the only LoRA bundle (boristown, E2B, 24 samples) has no
  score. All scored bundles use native `edit_file`/`write_file`; ours is the only one with an AST/BM25 localizer, a
  fuzzy heredoc editor and a finalize script. No public evidence for or against those three.
- **Budget and sampling are converged.** Every bundle hashed in batch A uses our exact `eval_config`, and all but
  one our exact sampling (T 0.2, top_p 0.95, 8,192 output, thinking 4,096). The exception is Idris v24 (T 1.0, top_p 0.95,
  top_k 64), one of the six 0.24 teams; his ledger (relayed second-hand) attributes v19 0.18 -> v24 0.24 to the
  sampling change alone, one draw each.
- **Scoring run** (Ryan Holbrook, 743063): tasks run sequentially; the scorer reads only the four `eval_config`
  keys; going over 12 h errors the whole submission (the proposed "unfinished = 0" fix was reconsidered).

### 2.2 Measured effects (third party; single runs unless stated)

| Lever | Result | Source |
|---|---|---|
| Thinking disabled | 23 vs 48 /129 | Ayush Thakur, 746250 (local, fast GPUs) |
| Thought summaries off | 35 vs 51 /129 | same |
| Tool calls 50 -> 25 (15-min cap) | 36 vs 50 /129, median runtime -29% | same |
| Time cap 6 / 10 / 15 min | 37 / 46 / 54 /129 | same (fast GPUs; Kaggle L4 ~1.25x slower per token than his sequential setup, 747857) |
| T 0.0 / 0.2 / 0.4 / 1.0 | 47 / 48 / 51 / 51 /129 | same |
| Thinking 2,048 / 4,096 / 6,144 | 50 / 48 / 48 /129 | same |
| Graph tools added | 50 vs 55 /129; all semantic searches empty | same |
| Analyzer sub-agent | +1 /129 | same |
| Coder-analyzer vs single coder | 16/70 vs 27/70 (p = 0.013); LB 0.12, 0.10, 0.06 | Dmitrii Gluzdov notebooks |
| Two voting reviewers | 13/70 vs 16/70 | same |
| Candidate list for repair (13 tasks x 5) | none 24, lexical 23, reranked 27 /65; earlier run: lexical 21, perfect localization 24 /65; 160 of 175 runs on never-solved tasks edited the right file | GemmaLoc notebook |
| Stronger teachers (DeepSeek V4 Pro, Qwen3.6-27B) in the same harness | 58-59 vs 53-54 /124; 15% of tasks flip between identical Gemma passes; union of 4 runs 73/123 | Ruijie Zhu, 747168 |
| LoRA SFT on trajectories | 0.0 on LB (alpha bug), 2/32 vs 4/32 base | icfoer 750713, Gluzdov |
| 12B model, same files | exceeded 12 h, no score; 3-4 vs 9-11 /31 locally | Gluzdov |

Ceiling facts: 37 of 70 dev tasks unsolved by 8 configurations (Gluzdov); 35 of 38 multi-file gold tasks never
solved by any config (Adam Johnson, 753524); 64 of 114 never solved (Gluzdov dataset). The 16th-ranked team (htn,
748051): "none of the top submissions have managed to get any improvements through finetuning".

### 2.3 Platform facts that matter
- vLLM 0.19.1 in the scorer drops a tool call emitted inside an unclosed thought (753521): ~1% of runs.
- The compaction summary call ignores the submission's sampling (753225). Tool results arrive double-JSON-encoded
  (744272), consistent with the backslash-count mismatches our S15 editor tier handles.
- Queue: one pending submission per team; ~14-61 h from submit to score (staff in 747519, victorzhong's draws); a
  failed run still uses the daily slot.
- Small-model bonus ($10,000, 751104): highest private-board submission on E2B/E4B; must be one of the team's two
  final selections. Host small-model board (notebook v13, ~12 h old): 311 teams, top 0.10 (6/58, 3 teams), 25 at
  0.08.

## 3. Our agent against the field

| Dimension | Ours (S12 -> S16 line) | Field | Gap / evidence |
|---|---|---|---|
| Agent | 1 LlmAgent | 1 LlmAgent | none; multi-agent measured neutral or harmful |
| Budget | 8 min / 28 calls / 80 turns / 240 s | identical | none, except calls (P4) |
| Sampling | T 0.2, top_p 0.95, no top_k | identical except Idris (T 1.0, top_k 64) | P1 |
| Editing | heredoc SEARCH/REPLACE editor via run_command (S12 panel: 0 arg errors in 480 calls; 6 of 48 editor calls not applied) | native edit_file; known parser mangling (73/208 malformed in our S1-S4) | ours is better on tool errors; no LB A/B |
| Localization | AST + BM25 localize.py, model re-ranks | grep in prompt | GemmaLoc: perfect localization adds ~0-3/65, so not the bottleneck |
| Hygiene | finalize.py (revert tests, compile, import check from S14) | prompt rules | Ayush 747857: prompt with a finalizer 2-4 test-patch conflicts vs 8-11 with an empty prompt |
| Validation | 24-task mixed panel, 1 run, gold-solvable only | most teams: LB draws | see below |
| Selection | pooled evidence (RESUME policy) | mostly best public draw | our policy is right for the private board |

Two repo facts found during this analysis:
1. **Our `agent/configs/sampling.yaml` comment says top_k "is dropped by LiteLLM for OpenAI-compatible endpoints".
   Locally this is false:** with the repo venv (LiteLLM 1.93.2), `get_optional_params(custom_llm_provider='openai',
   top_k=64, drop_params=True)` returns `extra_body: {'top_k': 64}`, and ADK's `lite_llm.py` forwards `top_k`. The
   scorer's LiteLLM version is not verified. The comment was not edited here (agent/ must equal the frozen
   candidate for the release gate).
2. **The dev panel barely discriminates.** Over all 12 panel runs (S1-S9, S12, S13, B1), only 5 of 34 gold-solvable tasks
   ever changed outcome; 13 were always solved and 16 never. S9 and S12 agreed on 23 of 24 tasks. A 24-task panel
   therefore measures ~5 informative tasks; it cannot detect a +1-2 task (hidden-set) effect, and our kernel only
   reaches 52 gold-solvable tasks because of missing test dependencies (Zbigniew Kirchner, 751487, reaches 127/129
   with a scorer-like sandbox built from public Apache-2.0 datasets).

Our own failure classes on the S12 panel (11 failures): 6 sessions ended on the 28-call cap after 182-349 s with
time left, 4 of them failed (rich_3935 and rich_3472 with empty patches, rich_3471, rich_4070 import break, the
last addressed by S14); 3 timeouts (fastapi_14419, rich_3944, rich_3930, which needs a new module); 4 wrong fixes
(fastapi_13920 wrong place, fastapi_15588 exact message, rich_3535 regex, rich_3675).

## 4. Prioritized plan

Costs: a 24-task panel takes ~2 h of L4x4 wall time (RESUME); the competition page says L4x4 consumes quota at 2x,
while Emanuele read ~1.6 h for the 14-task S13 panel, so budget 2-4 h of quota per 24 tasks and measure the first
panel after the 2026-10-31 reset. Quota left until the deadline: ~4.5 weeks x 30 h. Submissions: at most one per
day and one pending, so at most ~34 slots, fewer in practice; each is also a potential final.

### P1. Sampling: T 1.0, top_p 0.95, top_k 64 (Google's published Gemma recommendation, not re-checked today) - one variable on top of the current best
- Evidence: Ayush 746250, 129 local tasks: T 0.2 48, T 0.4 51, T 1.0 51 (single runs, +3 = within noise but
  same direction twice). Idris v19 0.18 -> v24 0.24 with sampling only (one draw each, second-hand, selection
  bias). Contrary: Budget-Aware files at T 0.4 drew 7 once (Gluzdov). top_k is forwarded (section 3, fact 1).
- Expected effect: mean 0 to +2 tasks; run-to-run variance up. Variance helps here: with the mean below the
  cutoff, a higher-variance final raises P(best of 2 >= cutoff) (table 1.4) and decorrelates it from a T 0.2
  final.
- Cost: 1 panel (2-4 h quota), 1 submission slot.
- Risk: more malformed calls or heredoc mistakes at T 1.0 (our editor needs exact markers); longer sessions (time
  limit). Measured on the panel before any submission.
- Offline validation: same 24-task mixed panel as S12 (`kernels/agent_eval/build.py --mix Textualize/rich=12
  fastapi/fastapi=12 --pools results/gold_check/pools.json`, seed 0), compared task by task with S12; with T 1.0,
  run it twice if quota allows. Pre-register: ship if SANITY passes (>= 20 finished, 120 x mean <= 11 h, editor
  missing after localize = 0), resolved >= S12's 13 minus 1 (non-inferiority: the goal includes variance),
  arg_errors and editor-not-applied rate not above S12's by more than 2.

### P2. Private-board strategy: timing and the two finals (no GPU)
- Evidence: tie rule (Rules, verified); band sizes (section 1.3); regression of best-of-many draws (section 1.3).
- Actions:
  1. Every submission is a potential final and its date is its tie-break. Submit the strongest candidate as early
     as possible; a later configuration must beat an earlier one by about a task in expected mean, not in one
     public draw, to be worth selecting.
  2. Select two finals that are different configurations (e.g. the best T 0.2 and the best T 1.0 candidate), by
     pooled panel + LB evidence, never by the single best public draw (already RESUME policy).
  3. Spend daily slots on candidates that are plausible finals. Panel-less micro-fixes (S14-S16: import check,
     backslash tier, prompt wording) are fine as draws, but each delays the next real candidate by a day. Whether
     a P1 candidate that passes its panel should jump ahead of S15/S16 in `submit_queue.json` is Emanuele's call
     (not changed here).
- Expected effect: avoids losing a medal on tie-breaks inside bands of hundreds of teams; size not estimable.
- Cost: none. Risk: none beyond choosing which queued tags ship.
- Validation: not applicable (rule-based).

### P3. A panel that can actually discriminate
- Evidence: section 3, fact 2 (5 informative tasks of 34); 751487 (127/129 gold patches pass in a scorer-like
  sandbox, public Apache-2.0 notebook and datasets, evaluation only, nothing goes into the submission).
- Action: rebuild the gold check with the scorer-like environment, then a fixed ~48-task panel: drop the 16
  never-solved tasks, keep a few always-solved controls, add unexplored gold-solvable fastapi/rich/requests tasks.
  Every candidate runs together with a control (current best) on the same panel; compare paired outcomes
  (discordant tasks), not totals.
- Expected effect on score: none directly; it is what makes P1/P4 decisions better than coin flips. Honest limit:
  even 48 paired tasks only detect effects of ~+4 tasks on the panel.
- Cost: one CPU kernel for the gold check (no GPU quota); a 48-task panel ~4 h wall (4-8 h quota).
- Risk: a scorer-like sandbox is not the scorer; datasets from another participant must be pinned by hash.

### P4. Tool-call cap 28 -> 36 with the 8-minute cap unchanged
- Evidence for: 6/24 S12 sessions stop on the call cap at 182-349 s with time left (4 of them failed); Ayush: 50 -> 25 calls cost
  14/129 (at a 15-minute cap on fast GPUs, where calls bind more than on L4). Against: Adam Johnson 753524: a
  154-run replay of a cap raise was net -1 and his budget-raise submission returned no score; Gluzdov: runs past 14
  calls rarely resolve (correlational); our S8 (more time) gained nothing and projected 11.68 h.
- Expected effect: 0 to +1 task. Cost: 1 panel + 1 slot.
- Risk: the hidden run time is not observable; a 12 h overrun loses the submission. Gate tighter than usual:
  120 x panel mean <= 10.5 h.
- Validation: P3 panel, paired against the same control; report how the capped sessions end.

### P5. Small-model bonus ($10,000): decision needed from Emanuele
- Facts: 311 teams on the host small-model board, top public 0.10 (6/58), 25 teams at 0.08. Eligibility requires
  one of the two final selections to be E2B/E4B.
- Cost: one final slot. Under table 1.4 the main-board odds then rest on one draw: with mean 10, P(>= 12) drops
  from 0.50 to 0.29 (binomial). Plus daily slots and quota for E4B development; known E4B QAT copying bug (drops a
  trailing "s") hurts exact-match edits (753277), where our fuzzy editor may help (unverified).
- Not recommended by default; it trades medal odds for a shot at prize money. Only Emanuele can weigh that.

### P6. Patch-correctness rules (low priority)
Rules aimed at the measured "right file, wrong fix" class: update parallel implementations (sync/async,
`__all__`, overloads), keep existing tests in the touched test file passing, check the import comes from the
checkout. Evidence: claims and single draws only; our S13 verify rule fixed 0 of 11 and cost time. One prompt line
each, only bundled with a P1/P4 candidate if its panel shows no time cost.

### Not recommended (evidence above)
Graph/embedding tools; analyzer, coder-analyzer or voting sub-agents; a separate rerank call; LoRA (no training
GPU, public attempts lost to the base model); the 12B or smaller models for the main board; turning thinking or
thought summaries off; any budget whose 120 x mean exceeds ~11 h. Exploratory and not advised with 34 days and one
submission per day: within-task best-of-k with `ParallelAgent` (pass@k headroom is real, 73 vs 54 /123, but the
budget is one shared context, `run_command` blocks the event loop, branches share `/workspace`, and choosing
between patches without the hidden tests is the unsolved part; no public bundle does it).

## 5. Open decisions for Emanuele
1. Run P1 (and P3) on the first quota after the 2026-10-31 reset, before more prompt micro-fixes?
2. If the P1 candidate passes its panel, may it go ahead of S15/S16 in `submit_queue.json`?
3. Small-model bonus: spend one final slot on E2B/E4B or keep both slots for the main board?
</content>
</invoke>
