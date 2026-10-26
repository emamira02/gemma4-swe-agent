# RESUME — Kaggle loop runbook (read this first after any interruption)

Everything long-running happens on Kaggle's servers (eval kernels, scored submissions): a reboot of this PC stops
nothing. State lives in git (`runs.csv`, `results/agent_runs/*.json`, this file) and in `STATE.json` (local).

## Automation (local scheduled tasks, Claude desktop app; run when the app is open, catch up on next launch)
- kaggle-loop (every 4 h): status sync, READY/BLOCKED decisions after a panel, submits the first READY entry.
- kaggle-improve (every 2 days, 10:20): traces -> one targeted change -> tests -> new tag -> GPU dev panel.
- kaggle-paper-final (once, 5 Nov 10:00): agent results into the paper, clean-commit rebuild, submission
  (asks Emanuele only for the final click if the website is required).

## History note
Commit ids before 2026-10-26 20:20 UTC were rewritten (messages, then owner noreply email; trees and dates
identical): results/commit_id_map.md maps the ids cited in candidate manifests and older notes.

## Resume in one command
    python tools/status.py
It is idempotent: refreshes submission scores into runs.csv, downloads a finished dev-panel eval, aggregates its
traces into results/agent_runs/<tag>.json, writes STATE.json, prints the next action. Then commit and push.

## Verified competition facts (read on kaggle.com 2026-10-26 ~20:50 UTC)
- Rules 2.2: "You may submit a maximum of one (1) Submission per day"; "You may select up to two (2) Final
  Submissions for judging". Team size max 5; entry and team-merger deadline 25 Nov; final submission deadline
  2 Dec 23:59 UTC; paper 12 Nov 23:59 UTC. Prizes: $65,000 (37k/18k/10k) + paper $35,000 (total $110,000).
- Kaggle staff, pinned thread 747519: a pending-submission limit separate from 1/day: a new submission is accepted
  only after the team's previous one has finished scoring. Queue ~33 h (mid-Oct) -> ~14 h; "most runs should finish
  within ~24h of submit now". So the real cadence is at most one scored submission per ~day, only if the next one is
  sent as soon as the previous finishes.
- Overview/Evaluation: the 12 h limit covers patch submission incl. sandbox setup, EXCLUDING patch validation.
- Allowed models (all agents of a submission must use the same one): gemma-4-31b-it-qat-w4a16-ct,
  gemma-4-12b-it-qat-w4a16-ct, gemma-4-e4b-it-qat-w4a16-ct, gemma-4-e2b-it-qat-w4a16-ct. PEFT LoRA adapters in
  adapters/<name>/ (adapter_config.json + adapter_model.safetensors), one per LlmAgent allowed.
- Winner license: Apache 2.0 (the repository needs a LICENSE before any prize claim).
- Known platform risk (forum, 10-21/22): unchanged bundles failing with "Notebook Threw Exception" (slow vLLM start
  on L4, ~1,200 s limit reported); a failed run still uses the daily slot.

## Submission policy (from 2026-10-26; replaces "submit only READY")
Every UTC day on which no submission is pending, submit one never-submitted frozen candidate that passes the
SANITY gate: rebuilds to its sha, official compile ok, panel finished on >= 20 of 24 tasks, resolved_on_solvable
>= 4, no infrastructure failure (editor/skills missing, crash loop). Among those pick the highest panel
resolved_on_solvable, newest on ties. The dev panel (24 tasks, 1 repo, 1 run) cannot rank candidates within
+-2 tasks; the public leaderboard (58 hidden tasks) is the better measurement, but one run has a 95% interval of
about +-9 points, so never read a 1-2 task difference as progress. Final selection (2 of them) by pooled evidence,
not by the single best public score.

## Hard rules
- One pending submission at a time (Kaggle). Every submission goes through `tools/kaggle_submit.py --tag Sx
  --hypothesis "..."` (validation + official compile + sha check + runs.csv). Never reuse a tag.
- The 12 h scoring limit is absolute: `eval_config.yaml` must keep worst case <= 11.5 h (builder enforces it).
- Never spend money. No paid compute. GPU = Kaggle quota only (L4x4 counts double; ~2 h per 24-task panel).
- Competition data never leaves `data/` (gitignored). No task text in committed results.
- Paper: `python -m locstudy report` must pass all machine-checked claims; <= 3,000 words.

## Current state (update after every step)
| Item | State |
|---|---|
| S1 (4e14db4d5e2f) | submitted 2026-10-12 16:50 UTC, COMPLETE, public score 0.15 (seen 2026-10-13 21:44 UTC) |
| S1 dev panel | 4/21 solvable resolved; 16 timeouts; 53 malformed calls (backticks); see results/agent_runs/S1.json |
| S2 (fbfe865bd968) | SKIPPED 2026-10-13 (superseded by S3: same panel resolves, fewer timeouts) |
| S3 (e1af59a2b337) | panel done 2026-10-13 (4/22 resolved, 12 timeouts, no_edit 5); submitted 2026-10-13 21:47 UTC, COMPLETE, public score 0.12 (seen 2026-10-16 11:14 UTC; below S1 0.15) |
| Queue | 2026-10-26 20:37 UTC: no pending submission, no READY entry (S4, S5 BLOCKED); S6 dev panel RUNNING |
| S4 (16a19a7ecd46) | panel done 2026-10-14 07:15 UTC: 5/22 resolved (best so far), 9 timeouts, empty 3, no_edit 2, BUT tasks_with_arg_errors 3 -> 8 (arg_errors 5 -> 43, 42 backtick) -> BLOCKED by rule; needs fix (new tag) |
| S5 (39038672b64d) | panel done 2026-10-26 20:34 UTC: 5/21 resolved, 12 timeouts, empty 10, no_edit 8, tasks_with_arg_errors 1 (arg_errors 4) -> BLOCKED (empty + no_edit 18 vs 5) |
| S6 (291a2befe7e9) | built + frozen 2026-10-26 (committed 19:42 UTC, 34ccfde) from S5: edits through run_command + heredoc SEARCH/REPLACE editor, edit_file/write_file removed; 31 bundle tests + Linux exec-chain check 13/13 (results/editor_check/); WAIT_PANEL (panel pushed 2026-10-26 20:37 UTC) |
| Paper | 2026-10-26: 4.10 rewritten from the pooled S1-S4 failure audit (results/failure_audit.json -> agent_summary "failure"): 59.3% rank-1 edited file, >= half of unresolved runs edited a gold file, edit_file 73/208 vs run_command 0/807 malformed; abstract agent sentence; SweRank (Reddy et al., ICLR 2026, arXiv 2505.07849, verified) in related work; compact table + paper/RESULTS_AGENT.md; build now fails above 3,000 words (2,968 now, room for ~2 more tag rows); 93 claim guards pass. Refresh: python -m analysis.failure_audit && python tools/agent_summary.py && python -m locstudy report |

## Submission queue (when nothing is pending, kaggle-loop submits the READY entry with the most panel resolves, newest on ties)
Candidates are frozen in candidates/<TAG>/ (bundle + sha); submissions always use the frozen copy (tools/kaggle_submit.py).
| Tag | Status | Change vs previous | Hypothesis |
|---|---|---|---|
| S2 | SKIPPED (superseded by S3 on 2026-10-13: tie on resolves, newest wins; S3 fewer timeouts) (panel: resolved 4/21 = S1; tasks with malformed calls 14 -> 5; timeouts 16 -> 14; empty patches 7 -> 9; no_edit 5 = 5) | backtick-free prompt/outputs, <=3 reads before edit, edit by call 6, 32-call cap | malformed calls and over-exploration cause most S1 timeouts |
| S3 | SUBMITTED 2026-10-13 (panel: resolved_on_solvable 4/22; timeouts 12; empty_patch 7; tasks_with_arg_errors 3; no_edit 5; timeouts+no_edit 17 vs S2 19 -> READY) | S2 + localize shows rank-1 source in anchored mode (edit without a read), write_file /tmp misuse explained, finalize deletes /workspace/tmp | S2 traces: 10-24 reads per task and first edit at 122 s median dominate the 14 timeouts |
| S6 | WAIT_PANEL (panel pushed 2026-10-26 20:37 UTC) | S5 minus edit_file, write_file and replace_lines.py; plus skill script edit.py, installed by localize.py (and by finalize.py on an empty patch) to /tmp/swe/edit.py and called from run_command with the code in a quoted heredoc: SEARCH/REPLACE blocks (exact, whitespace, indentation and copied-line-number tiers; unique match; all-or-nothing; compile guard; atomic write keeping EOL/mode; idempotent via a journal in .git), line ranges, new files; an unquoted heredoc is recovered raw from /proc | the gemma4 call parser emits keys alphabetically, so edit_file's long new_string precedes old_string and a stray closing backtick swallows old_string: edit_file 73/208 calls malformed in S1-S4 (S4 41/78; 2 solvable tasks lost with no edit, NO_EDIT_TOOL), run_command 0/807 (incl. 177 python -c, 26 heredocs). One code value per call removes the failure class |
| S5 | BLOCKED 2026-10-26 20:36 UTC (panel: resolved_on_solvable 5/21; timeouts 12; empty_patch 10; no_edit 8; tasks_with_arg_errors 1 (arg_errors 4 vs S4 43); failure_audit: NO_EDIT 10, WRONG_FILE 1, RIGHT_FILE_TIMEOUT 2, RIGHT_FILE_WRONG_FIX 3, NO_EDIT_TOOL 0; replace_lines never called. Rule: empty_patch + no_edit 18 vs S4 3 + 2 grows by more than 2 = new failure mode -> BLOCKED. Malformed calls fixed, but 10 sessions never edited) | S4 + skill script replace_lines.py (write_file the new lines to tmp_new_lines.txt, then replace lines A-B by number; refuses a result that does not compile) + prompt rule: after a missing-parameter or twice-not-found edit_file error never resend edit_file for that change, use the line fallback | S4 traces: 41/78 edit_file calls lost old_string in the call serialization (7 tasks), resent unchanged up to 13 times (identical_repeat 29); write_file (one code value) lost a field only 4 times in 76 across S1-S4 |
| S4 | BLOCKED 2026-10-14 (panel: resolved_on_solvable 5/22; timeouts 9; empty_patch 3; tasks_with_arg_errors 8 vs S3 3 (arg_errors 43, backtick 42 vs 5); no_edit 2; empty+no_edit 5 vs 12 ok, but more arg errors = new failure mode per rule) | S3 + thinking_budget 2048 -> 1024, prompt rule: think briefly, edit the most plausible option and let the check decide | capped 2,048-token thinking turns (~60 s each, 28-29% of agent time in S1-S3) cause the late/no edits behind 7 empty patches and 12 timeouts |

Decision rule for S6 after its panel (written 2026-10-26, before the panel): READY if resolved_on_solvable >= the best
panel so far (S4 = 5, or S5's if higher), tasks with a malformed edit attempt (failure_audit malformed_edits > 0) <= 1,
editor_not_applied / editor_calls <= 0.35, NO_EDIT_TOOL = 0, and no new failure mode (editor never installed, unquoted
heredocs that corrupt code, scratch files in the patch, empty_patch + no_edit above S4's 3 + 2 by more than 2);
otherwise BLOCKED. Report editor_calls, editor_not_applied, editor_unquoted and the failure_audit categories next to it.
Decision rule for S5 after its panel: READY if resolved_on_solvable >= 5 (best so far: S4 = 5), tasks_with_arg_errors < 8 (S4)
and arg_errors < 43, and no new failure mode appears (e.g. replace_lines misuse: wrong line ranges, NOT APPLIED loops, scratch
file left in the patch; more empty patches + no_edit than S4's 3 + 2 by more than 2); otherwise BLOCKED.
Decision rule for S4 after its panel: READY if resolved_on_solvable >= 4 (best so far: S1/S2/S3 = 4), empty_patch + no_edit do not grow vs S3 (7 + 5)
and no new failure mode appears (e.g. more arg errors or truncated-thought turns with no tool call); otherwise BLOCKED.
Decision rule for S3 after its panel: READY if resolved_on_solvable >= 4 and timeouts + no_edit do not grow vs S2.
Decision rule for S2 after its panel (applied 2026-10-13): READY if resolved_on_solvable >= S1's (4) and tasks_with_arg_errors drops
by at least half; otherwise fix the cause seen in the traces first (new tag), never submit a known regression.

## Findings S5 (dev panel 2026-10-26; 21 gold-solvable, 5 resolved)
- The fallback removed malformed calls (tasks_with_arg_errors 8 -> 1, arg_errors 43 -> 4) but was never used:
  edit_file simply broke less often in this run. Run-to-run noise at temperature 1.0 is part of it.
- New dominant loss: 10 NO_EDIT sessions (S4 3), 8 of them timeouts, with 6-35 calls each and no edit attempt.
- Over-exploration is general, not S5-specific: reads before the first edit (read_file + cat/sed/head) median 4 in
  S4 and 5 in S5, more than the prompt's limit of 3 in 13 (S4) and 15 (S5) of 24 tasks; grep before the first edit
  91 (S4) -> 109 (S5), python probes 29 -> 48. The "at most 3 reads before your first edit" rule is not obeyed.
- S6 keeps the same prompt steps, so the same risk applies; its rule blocks it if empty_patch + no_edit > 7.
  Candidate change after S6 (one variable): make the edit deadline concrete in the tool outputs themselves (e.g.
  localize ends with an explicit "next call: the editor on <rank-1 range>" and the editor/read outputs carry a
  call counter), rather than another prompt sentence.

## Findings S1-S4 failure audit (2026-10-26, python -m analysis.failure_audit -> results/failure_audit.json)
Per task and tag, first match wins: GOLD_UNSOLVABLE / RESOLVED / NO_EDIT_TOOL (>= 2 edit attempts failed at the tool
level, no source write) / NO_EDIT / WRONG_FILE / RIGHT_FILE_TIMEOUT / RIGHT_FILE_WRONG_FIX (right file, submitted, fails).
| Tag | resolved | NO_EDIT_TOOL | NO_EDIT | WRONG_FILE | RIGHT_FILE_TIMEOUT | RIGHT_FILE_WRONG_FIX | unsolvable |
|---|---|---|---|---|---|---|---|
| S1 | 4 | 0 | 6 | 2 | 7 | 2 | 3 |
| S2 | 4 | 2 | 6 | 3 | 3 | 3 | 3 |
| S3 | 4 | 0 | 6 | 2 | 5 | 5 | 2 |
| S4 | 5 | 2 | 3 | 2 | 3 | 7 | 2 |
- Localization is not the binding constraint on this panel: localize ranks a file the gold patch edits first in 13-14
  of 24 tasks in every tag, yet 4-5 are resolved. The losses are after localization.
- The same four tasks (3006, 3067, 3882, 3905) are resolved by every tag; S4 adds 3777. Version-to-version panel
  differences are one task: within run-to-run noise, never evidence on their own.
- Tool level: edit_file 73/208 calls malformed over S1-S4 (S4 41/78), write_file 4/76, run_skill_script 33/159 (all S1,
  fixed in S2), read_file 3/825, run_command 0/807. Cause (vLLM gemma4 tool parser, v0.19.1): string values end only
  at the <|"|> token and keys come out alphabetically; a value closed with a backtick swallows every later key
  (edit_file: new_string swallows old_string; write_file: content swallows filepath). On timeout the working tree is
  still graded (agent_runner fallback diff), so timeouts lose tasks only through unfinished or wrong edits.
- Next largest class after the tool fix: RIGHT_FILE_WRONG_FIX (S4 7). Candidate next change after S6: a cheap
  reproduce-then-verify step (run the related test or a python -c probe of the issue's example before and after).
- Post hoc, descriptive (confounded by task difficulty), pooled S1-S4 runs: median first edit 47 s in RESOLVED (17),
  131 s in RIGHT_FILE_WRONG_FIX (17), 209 s in RIGHT_FILE_TIMEOUT (18). Wrong fixes were usually checked (14/17 ran a
  check after the edit) but almost never with pytest (1/17; resolved 6/17): self-written python -c probes confirm the
  model's own reading of the issue. Hypothesis for S7 (pre-register before building): after the first edit, run the
  RELATED TESTS file of localize once (python -m pytest -x -q FILE 2>&1 | tail -25) before any other check.
- Timing (kernel duration_s = container setup + agent + hidden-test verification per task): mean 241-275 s, max 528 s
  (rich_3772, slow tests) on the panel. Builder worst case 120 x (5.0 + 0.5) + 15 min = 11.25 h; S1 and S3 hidden runs
  finished inside the 12 h limit. Keep max_time_minutes at 5.0: 5.5 would leave no margin (120 x 6.0 = 12 h).

## Findings S4 (dev panel 2026-10-14, analysed 2026-10-26; 22 gold-solvable, 5 resolved)
- Largest measured failure mode: broken edit_file calls. 41 of 78 edit_file calls (S1 17/52, S2 15/44, S3 0/34) came
  back "mandatory input parameters are not present: old_string": the model closed the first code value with a
  backtick or plain quote instead of its string delimiter, so the rest of the call (old_string) was swallowed into it.
  7 tasks hit it (3063 x13, 3882 x10, 3296 x5, 3472 x5, 3067 x4, 3521 x1, 3470 read_file path x1); the model then
  resent the identical call (identical_repeat 29 of 554 calls), ignoring the generic never-repeat rule.
  Outcome: 3063 timeout on a known fix, 3472 empty patch at timeout, 3882/3067 resolved only after 10/4 wasted calls.
- Triggers: values with quotes, backslashes, regex or triple quotes (3063, 3067, 3472, 3521), but also plain code
  (3882, 3296): not avoidable by content rules alone. write_file (one code value) lost a field 4 times in 76 calls.
- Other classes unchanged vs S3: timeouts 9 (3063, 3469, 3472, 3506, 3782, 3930, 3935, 3942, 3953), empty 3 + no_edit 2
  (3782, 3942), first edit median 115 s (S3 ~200 s on failures): the S4 thinking cut worked on time.
- Confound: S3 (2,048 thinking) had 0 broken edits, S4 (1,024) 41; S1/S2 (2,048) 17/15, so not clearly the budget;
  kept 1,024 (best resolves). If S5 still shows many broken calls, test 2,048 + fallback next.
- Change chosen (S5): line-range fallback script + explicit recovery rule (see queue).

## Findings S3 (dev panel, 2026-10-14; 18 unresolved solvable tasks, traces + gold comparison)
- Same 4 tasks resolved in S1, S2, S3 (rich_3006/3067/3882/3905); S1 public score 0.15 matches the panel (~4/24).
- Timeouts are graded on the working tree, so timeouts are not lost per se; the outcome classes are:
  empty/effectively empty 7 (3063, 3472, 3506, 3521 scratch file only, 3935, 3938 raw tool-call text, 3942),
  right site wrong logic 5 (3471, 3675, 3777, 3782, 3953), wrong site 2 (3772 hang exit 124 in all runs, 3944 vague
  issue), broken/not feasible in 5 min 2 (3930 needs a 12.7k-line data module, 4070 128-line refactor),
  right logic incomplete 1 (3535), right fix plus harmful extra edit 1 (3470).
- Localization is not the bottleneck: gold file in localize top-5 for 15/18, gold file read in 15/18.
- Time: thinking turns hitting the 2,048 cap (~2,100 completion tokens, ~35 tok/s, ~60 s each): 20/18/20 per panel
  in S1/S2/S3; turns >=1,500 tokens = 28-29% of all agent time in every run. Median first source edit ~200 s on the
  18 failures; 6 tasks first edit >=260 s or never; pytest run only 3 times on the 18.
- Change chosen (S4): thinking budget 1024 + brief-thinking rule (targets the largest measured time sink; prompt/
  localize rules for the right-site-wrong-logic class are the next candidate once time is freed).

## Timeline
- S1 score: ~14 Oct (±12 h). Each further submission: ~2 days from submit to score.
- Paper: add agent results after 3–4 scored submissions; final build from a clean commit; submit by 8 Nov
  (deadline 12 Nov 23:59 UTC).
- Main competition: iterate until final selection, deadline 2 Dec 23:59 UTC (pick 2 submissions).

## Commands
    python tools/build_submission.py --tag Sx          # validate + official compile + zip + submit notebook
    python kernels/agent_eval/build.py --tag Sx         # dev-panel kernel (same 24 rich tasks, seed 0)
    python -m kaggle kernels push -p kernels/agent_eval # run it on Kaggle GPUs (~2 h)
    python tools/kaggle_submit.py --tag Sx --hypothesis "..."
    python -m analysis.agent_traces results/kaggle_eval_Sx --out results/agent_runs/Sx.json
    python -m pytest -q tests/ ; third_party/venv/Scripts/python -m pytest -q tests/test_agent.py
