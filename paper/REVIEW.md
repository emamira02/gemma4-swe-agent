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
- Agent panel: one repository (rich), solvability 21 or 22 of 24 depending on the run (environment flakiness in the
  gold check; the denominators are reported per tag).
- File-level rank 1 in rich is easier than in larger repositories (few, large modules); 4.10 avoids generalising it.

## E. Clarity (3.5/5)
- Dense: many intervals per sentence. The abstract is long (~330 words) but carries the four findings with numbers.
- Terminology is consistent (edited symbol / edited file, anchored / anchor-free, post hoc).
- Figures 1-4 exist; check legibility at Kaggle writeup width before submission.

## Highest-value remaining actions
1. Public code link (approval) -> Reproducibility.
2. After the S6 panel: one guarded sentence on whether the single-argument editor removes malformed edits.
3. Kaggle Writeup formatting check (figures, tables, word count as counted by the site).
