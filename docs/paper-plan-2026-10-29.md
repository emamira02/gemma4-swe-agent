# Paper track plan (gemma-4-developer-agent-paper, due 2026-11-12 23:59 UTC)

## Checkpoint 2026-11-02 22:30 UTC (read this first; the 29 Oct plan below is history where they differ)
Verified this session (repo main, kaggle CLI, gh, kaggle.com pages):
- Deadline 2026-11-12 23:59 UTC; entered in paper and main. No new paper-track discussion thread since the
  2 Nov inventory (newest 754918). Host, 751804: "Github should work for sharing code" (paper track).
- The GitHub repository is PUBLIC since its creation (2026-10-09 16:58 UTC, PublicEvent), not private as the
  29 Oct plan says. Main rules 6.b: publicly shared Competition Code must also be shared on the competition's
  Kaggle forum or notebooks. OPEN: owner decision.
- H1-H3 chronology holds: LLM kernel v1 died of CUDA OOM (no model output); 6a28d29 (H1-H3) 16:33:42 CEST,
  model outputs on disk 16:48:55 CEST, 10 Oct (git and file timestamps; Kaggle kernel versions not checked).
- `python -m locstudy report` rebuilds PAPER.md byte-identically from results/*.json. results/summary.json was
  recomputed from data/ (604a429): all 1,225 values identical, provenance now clean commit 6ac0a73.
- F1 done (8229c35, a5a7d86): "Recall@k" renamed Hit@k (keys unchanged, earlier name stated in Methods);
  4.10 eras marked as system comparisons; per-call serialization evidence (analysis/serialization_audit.py:
  S1-S5 77/77 malformed edit_file calls carry old_string inside new_string, after a backtick 72 or quote 5;
  B1 57/57); paper/CLAIMS.md (every number and guard with key and status) and paper/WORDCOUNT.md
  (gate 2,993; 2,732 without references and markdown-only tokens).
- kaggle-loop run of 2026-10-31 20:20 UTC still shows "running" (no activity since 20:20:44): same pattern as
  the 28 Oct incident; 1 Nov had no submission. Not touched here.

Novelty audit (one reader through a summarising fetch tool; verify each figure before citing it):
| Claim | Nearest prior | Verdict | Remaining difference / discriminating check |
|---|---|---|---|
| C1 anchors stratify localization | arXiv 2610.33958 (25 Oct 2026: hop depth from issue-mentioned code, Gemma 4 E4B, McNemar+Holm; no results for its "no mention" bucket); LocAgent 5.3; Agentless 6.1; SweRank lexical-overlap bins | partly known | per-signal results on the anchor-free stratum; show anchor status predicts hits beyond lexical overlap (CPU, post hoc) |
| C2 untuned Gemma 4 31B re-rank of BM25 top-50 | SweRank (fine-tuned listwise; untuned GPT-4.1 strong; "retrieval not the bottleneck"); 2607.11046 (file level, Qwen 32B, top-20) | partly known | untuned quantized offline model, symbol level, signatures only, pre-specified on anchor-free issues; pool coverage explains the opposite bottleneck to SweRank |
| C3 reading budget | EXAM score (effort before first fault) | partly known | token-denominated variant; keep as a cost metric, not a contribution |
| C4 serialization failure | ingredients public (template sorts keys; parser takes the rest of an unterminated string; gemma4-agent-lab PR #20 symptom, no diagnosis) | mechanism not found | per-call evidence now in repo; causal A/B (rename keys so old text sorts first) needs GPU |
| C5 losses after localization | arXiv 2511.00197, 2610.33958, 2607.09691 | known (direction) | setting only |
| C6 evaluation under 1 submission/day | arXiv 2609.17394 (discordant instances, McNemar+Holm), 2602.07150 | partly known | drop or one sentence |

Proposal for F2 (needs the owner's OK before the rewrite): two contributions instead of six. Central: issue
anchors decide which signals work, and the untuned competition model as re-ranker closes most of the anchor gap
(pre-specified H2), moving the bottleneck to candidate generation. Secondary: the offline agent's losses come
after localization, and one of them is a serialization failure diagnosed per call. Related work rewritten against
2610.33958, SweRank, 2607.11046, 2607.09691 and in-competition work (748395, 750732, BudgetAudit, codegraph-loc).
CPU-only additions: lexical-overlap control for C1/C2 (post hoc, declared). No new inference unless approved.

F2 done 2026-11-02 (owner: "Sì, procedi con F2"). Registered post hoc results (docs/posthoc-anchor-analysis-2026-11-02.md):
the re-rank does not narrow the anchor gap (BM25 minus re-rank +3.0 pp [-14.8, 22.0]); the gap splits into pool
reachability +22.8 pp [7.5, 37.7] and ranking +6.7 pp [-3.1, 17.6]; the anchor odds ratio stays above 1 with lexical
overlap controlled (re-rank 4.31 [2.07, 10.60]). The earlier idea "the re-rank closes the anchor gap" was false and
is not in the paper. The "Proposed thesis" below is history; the paper follows the two-contribution plan.
Next: fresh-eyes review (5-6 Nov row), figures at writeup width, then notebook and writeup draft.

## Verified facts (competition pages, read 2026-10-29)
- Submission: a Kaggle Writeup with title and subtitle, abstract, introduction, methods and experiments, related
  work and citations; **at most 3,000 words**; unpublished research; non-archival. Optional: a public notebook in
  "Project Links" (a private notebook attached there is made public automatically after the deadline) and a public
  PDF link. Drafts not submitted by the deadline are not judged.
- Judging: Novelty, Quality (generality beyond the competition), Relevance, Verifiability, Clarity, each 0-5, equal
  weight; scores are not shared; ties go to the earlier entry. Listed judge: Elan Markowitz (Google).
- Prizes ($35,000): Overall Best Paper $15,000; Best New Resource $10,000; Best New Application $10,000. No medals.
  420 teams, 449 submissions so far.
- Rules that constrain us: winners license the submission and its code under an OSI licence (repo is Apache 2.0) and
  deliver reproducible code; competition data must not be redistributed; in the main competition, public code
  sharing must happen on Kaggle (notebooks or forum), so the GitHub repository stays private until 2 Dec.
- Not verified: whether submitted writeups are visible to other teams before 12 Nov (the built-in browser is not
  signed in to Kaggle).

## Starting point
`paper/PAPER.md` ("Anchors Decide", 2,984 words, 93 machine-checked claims, every number generated from
`results/*.json`). Internal review (`paper/REVIEW.md`): novelty 3, statistics 3.5, reproducibility 3 (4.5 with a
public code link), method 3.5, clarity 3.5. What is stale or weak:
1. Section 4.10 covers only S1-S5 on a rich-only panel; S6-S13, B1 and the mixed panels are missing.
2. The reproducibility section cites the private GitHub repository.
3. The paper is a localization study, while the most practical, generalizable results came later.

## Proposed thesis
"Anchors decide localization, but localization is not what limits an offline agent." Three parts, one story:
1. **Localization (kept, compressed by ~25%).** The pre-registered measurement: anchor modes, mode-dependent
   fusion, reading budget, the model as re-ranker (pre-specified H1-H3).
2. **What limits the agent (rewritten 4.10, new section).**
   - Tool-call serialization: with the scorer's vLLM gemma4 parser, tools with two code-valued string arguments
     break (edit_file 77/248 malformed in S1-S5). After moving edits to one argument (heredoc editor), malformed
     calls fell from 119 of 2,655 (4.5%, S1-S5) to 8 of 2,056 (0.4%, S7, S8, S9, S12; failure_audit definition); the
     public edit_file prompt on the same harness (B1) had 61 of 625 (9.8%). Descriptive, different configurations: stated as such.
   - After localization: the policy ranks an edited file first in 57.9% of solvable runs (S1-S5), yet only 10 of 85
     unresolved runs edited the wrong file; the rest are right-file wrong fixes, timeouts and no edits; the mixed panel shows fastapi (long PR descriptions) far more solvable than rich
     (titles): 9/12 vs 3-4/12.
3. **Evaluating agents under one submission a day (new).** Over 12 panel runs only 5 of 34 gold-solvable tasks ever
   changed outcome (13 always solved, 16 never); public scores move in steps of 1/58 and the board keeps each team's
   best draw. Consequences that transfer to any small-budget agent work: panels of discordant tasks, paired
   comparisons, pre-registered decision rules, a release gate. This is the "Quality" (generality) argument.
4. Optional, only if the P1 panels finish by 3 Nov: the S17 vs S16ctl sampling comparison as one guarded,
   descriptive row (temperature 1.0 vs 0.2).

Target prize: Overall Best Paper. Best New Resource only if the code is public (the claim-guarded report builder and
the in-container localization and editing skills would be the resource).

## Work plan (CPU only; Kaggle GPU stays reserved for the main competition)
| Dates | Work | Output |
|---|---|---|
| 29-30 Oct | Plan, Emanuele's decisions below | this file |
| 30 Oct-2 Nov | DONE 29 Oct (eras, stability, per-repo, era table in 4.10; build green at 2,992 words). Extend analysis to all panels: failure audit for S6-S13 and B1, per-repository splits, outcome stability metric, serialization table, claim guards; tests | results/*.json, guards |
| 31 Oct-1 Nov | P1 panels (already scheduled, p1-panel-1..4) | optional row; DROPPED 2 Nov (S16ctl verdict has no owner task; not needed for the two-contribution paper) |
| 2-4 Nov | DONE 2 Nov (2db4f35, owner OK for F2 in chat): rewrite around two contributions, registered post hoc anchor analyses (cd93427, 55ac7a9), serialization audit, related work vs nearest priors; build green at 2,911 words | paper/PAPER.md |
| 5-6 Nov | DONE 2 Nov (c3c581e): independent review, 15 findings, responses in paper/REVIEW.md (2 open: publish text-free model ranks; manual label sample). Still to do: figure legibility at writeup width | REVIEW.md |
| 7-8 Nov | Code notebook (if approved) and writeup draft on Kaggle (Claude in Chrome, Emanuele signed in); word count as the site counts it | draft writeup |
| 9 Nov | Clean-commit build, Emanuele confirms in chat, submit | submitted writeup |
| 10-12 Nov | Buffer only | |

## Decisions (Emanuele, chat 2026-10-29)
- 2026-11-02 (chat, supersedes the code decisions below where they differ): the GitHub repository stays PUBLIC
  ("Keep it public, post the link"); its link is posted on the main competition's Kaggle discussion forum to meet
  General Rule 6.b. The paper cites it in section 8. "Study only" no longer applies: the agent bundles are public.
- Code: DECIDED (a), a Kaggle notebook in Project Links, private until 12 Nov and public afterwards.
- Code contents: DECIDED (Emanuele: "Yes, study only"): study and analysis code only (localization study, panel
  aggregates in results/agent_runs, the analysis that produces every number); the agent's skill scripts and prompt
  are described in the text and released after 2 Dec, because the notebook becomes public 20 days before the
  main-track deadline.
- kaggle-paper-final: DECIDED, moved to 9 Nov 10:00 with a prompt matching this plan (final build, writeup draft,
  stop before Submit).

## Decisions as first proposed
1. Code for verifiability: (a) a Kaggle notebook attached in Project Links, private until the deadline and then
   made public automatically (rules-compliant, recommended); (b) no code, writeup only (weaker on Verifiability).
2. What the code contains before 2 Dec: (a) the localization study and analysis code plus the three skill scripts
   that the paper describes (recommended); (b) study code only (keeps the agent's scripts away from main-track
   competitors until 2 Dec, but agent claims become harder to verify).
3. The scheduled task kaggle-paper-final (5 Nov 10:00) predates this plan and would edit the paper mid-rewrite:
   move it to 9 Nov with a prompt matching this plan (final build, writeup prepared, stop before the submit button),
   or delete it and finish the paper in the interactive session.
4. The final click on "Submit": the writeup submission is approved, but it is confirmed in chat on the day.
</content>
</invoke>
