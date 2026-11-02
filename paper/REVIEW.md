# Independent review of PAPER.md, 2026-11-02 (build 2db4f35; responses in c3c581e)

A reviewer with read access to the repository, given the paper and not the authors' conclusions, checked about 60
numbers against results/*.json through CLAIMS.md (no transcription error) and raised 15 findings. Each was checked
against the code and history before acting; one detail of the review did not hold (the main setting is not the
best on the label-strictness axis, 0.325 vs 0.330 at min_cov 0.01; it is the best on the three ranking axes).

| # | Finding | Response |
|---|---|---|
| 1 | Q2 read with a test other than the registered one | Registered criterion applied: share 77.4% [45.0, 115.6], split not resolved; claim removed from abstract and 5.2 |
| 2 | "Anchors decide which signals work" fails at Hit@5 (BM25 has the gap too) | Title and claim (1) made associational; structure-vs-BM25 difference stated only in depth |
| 3 | "Fixed in advance" contradicted by c245e7f/4ec5ed4 | Verified; only H1-H3 called pre-specified; robustness states the main setting is the best per ranking axis |
| 4 | "Registered before computing" and a wrong addendum time | Heading states what was known; addendum time corrected to the git record (cd93427 22:22:04, 55ac7a9 22:24:59 UTC) |
| 5 | Serialization failure explains few losses | Stated: 9 of 85 unresolved runs; added 30 of 35 no-edit runs read a gold file |
| 6 | run_command 0/1,047 cannot test the rule; write_file counterexample | Rule restated (code as the only or last argument); write_file 4/94 reported |
| 7 | Partial reporting of the declared family; "level with" | All non-significant members named; top-20 result of 4.3 added; equivalence wording replaced by the interval |
| 8 | Q1 vs RRF+ and unfittable resamples missing; H1 restates H2; overlapping exploratory tests | All reported in 4.6 |
| 9 | Model outputs and traces not public; stale agent_summary | agent_summary refreshed; per-call serialization records published without text; model rows and traces stay private (task text) - OPEN: whether to publish text-free per-task model ranks |
| 10 | Related work understates prior work | IR bug-localization work on report content added (verified on Crossref); remaining difference stated per neighbour |
| 11 | Label audit not independent | Labels called rule-based; the @@-header check named as the independent one; 16 unmatched hunks named. OPEN: no manual label sample reported |
| 12 | Re-rank, JSON parse rate and cost misdescribed | Re-rank picks 10 of 50 with docstring line; JSON enforced by the server; cost is both calls under batching; mean tokens rounded |
| 13 | Shifting denominators | 114 in the abstract; all hop counts; table column "all tools"; agent panel scoped to S1-S5 |
| 14 | One estimate with two intervals | Baseline intervals taken from the study; the post hoc analysis names its stratified resampling |
| 15 | Undefined terms | RRF/RRF+, anchored (Identifiers+), H1-H3 defined in Method; MRR dropped |

# Internal red-team review of PAPER.md (2026-10-26, build 2,968 words, 93 claim guards)

Simulated scores are an internal tool (0-5), not a prediction of the judges. Each issue lists what was done or what
is still open. Criteria of the paper track: novelty, quality, relevance, verifiability, clarity (equal weight).

## A. Novelty (3/5)
- Re-ranking retrieved candidates with an LLM for localization is established: SweRank (Reddy et al., ICLR 2026,
  arXiv 2505.07849) trains a retriever and a listwise re-ranker. DONE: cited; the paper's distinct claims are the
  anchor-conditioned measurement, the reading-budget metric, the untuned offline quantized competition model as
  re-ranker, and the end-to-end decomposition of an agent's losses.
- The tool-call serialization finding (alphabetical argument order + delimiter-only string termination: 73/208
  two-code-argument calls malformed vs 0/807 single-argument calls) is new and practical, but rests on one serving
  stack (vLLM 0.19.1 gemma4 parser) and four configurations of one agent. OPEN: S6 panel tests whether a
  single-argument edit channel removes the failure class; only then may the paper say so (guarded).
- Agentless / LocAgent / RepoGraph comparisons are qualitative (different benchmarks); keep it that way.

## B. Statistical validity (3.5/5)
- 114 labelled tasks, rich and fastapi dominate; per-repository results differ. Stated in 4.7 and Limitations.
- Several headline comparisons are post hoc (4.3, 4.4, 4.8, re-rank in both modes, ceiling); each is labelled and the
  pre-specified ones (H1-H3, commit 136a864) are separated. Holm within families.
- 4.10 pools 96 task runs of 24 tasks over 4 configurations: not independent; DONE: stated in the text, no test run
  on pooled counts, only descriptive shares with claim guards.
- One greedy model run (temperature 0, thinking off) for 4.9; the agent runs at temperature 1.0 with thinking on, so
  4.9 does not transfer numerically to the agent (stated implicitly; consider one sentence if words allow).

## C. Reproducibility (3/5 now; 4.5/5 with a public code link)
- Every number is generated from results/*.json and checked at build time; data hashes, commit and parameters are
  recorded; prompts hashed; frozen agent candidates rebuild byte-identically.
- OPEN (needs Emanuele's approval, external action): the repository is PRIVATE while the paper says "released as
  code" and cites scripts. Before 12 Nov either make emamira02/gemma4-swe-agent public or publish a cleaned copy.
  Pre-publication scan done 2026-10-26: no file under data/, no *.jsonl, no secrets-like strings, no task text and no
  reference/test patch lines anywhere in the git history (1.6 MB of history checked against all 129 tasks).

## D. Methodological limitations (3.5/5)
- Reference patches are one valid fix among many; module-level edits are excluded from symbol labels (counted).
- Pre-training contamination of the four public repositories: stated; the private hidden set is the real test.
- Agent panel: one repository (rich), solvability 21 or 22 of 24 depending on the run. The difference is one task:
  the same reference patch of rich_3782 (3,475 chars) failed its tests in the S1/S2 panels and passed in S3/S4 with
  unchanged kernel code; its hidden test is a width-dependent rendering test (tests/test_syntax.py). Cause not
  established (gold test outputs were not kept); denominators are reported per tag, never pooled across them silently.
- File-level rank 1 in rich is easier than in larger repositories (few, large modules); 4.10 avoids generalising it.

## E. Clarity (3.5/5)
- Dense: many intervals per sentence. The abstract is long (282 words, including the section heading) but carries the four findings with numbers.
- Terminology is consistent (edited symbol / edited file, anchored / anchor-free, post hoc).
- Figures 1-4 exist; check legibility at Kaggle writeup width before submission.

## Highest-value remaining actions
1. Public code link (approval) -> Reproducibility.
2. After the S6 panel: one guarded sentence on whether the single-argument editor removes malformed edits.
3. Kaggle Writeup formatting check (figures, tables, word count as counted by the site).
