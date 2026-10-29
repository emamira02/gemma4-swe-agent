# Paper track plan (gemma-4-developer-agent-paper, due 2026-11-12 23:59 UTC)

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
     calls fell from 125 of 2,655 (4.7%, S1-S5) to 4 of 2,370 (0.2%, S7-S13); the public edit_file prompt run on
     the same harness (B1) had 57 of 625 (9.1%). Descriptive, different configurations: stated as such.
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
| 30 Oct-2 Nov | Extend analysis to all panels: failure audit for S6-S13 and B1, per-repository splits, outcome stability metric, serialization table, claim guards; tests | results/*.json, guards |
| 31 Oct-1 Nov | P1 panels (already scheduled, p1-panel-1..4) | optional row |
| 2-4 Nov | Rewrite: abstract, contributions, new sections 5-6, compressed 4.1-4.8, limitations, reproducibility; build passes at <= 3,000 words | paper/PAPER.md |
| 5-6 Nov | Fresh-eyes review against the five criteria; clarity pass; figure legibility at writeup width | REVIEW.md |
| 7-8 Nov | Code notebook (if approved) and writeup draft on Kaggle (Claude in Chrome, Emanuele signed in); word count as the site counts it | draft writeup |
| 9 Nov | Clean-commit build, Emanuele confirms in chat, submit | submitted writeup |
| 10-12 Nov | Buffer only | |

## Decisions (Emanuele, chat 2026-10-29)
- Code: DECIDED (a), a Kaggle notebook in Project Links, private until 12 Nov and public afterwards.
- Code contents: PENDING. Recommended: study and analysis code only (localization study, panel aggregates in
  results/agent_runs, the analysis that produces every number); the agent's skill scripts and prompt are described
  in the text and released after 2 Dec. Reason: the notebook becomes public 20 days before the main-track deadline
  and Emanuele wants to avoid others building on his work there.
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
