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

## Incident 2026-10-28: no automatic submission for ~20 h
- The kaggle-loop run started 2026-10-28 03:20 UTC stayed "running" after its second tool call (a Bash call, 8 s
  after start; the transcript does not show why - most likely an unanswered permission prompt, UNVERIFIED). While
  it hung, the scheduler started no further kaggle-loop run, so S12's score and the free slot were never acted on;
  S14 was submitted by hand at 23:23 UTC. Stopped 2026-10-28 ~23:35 UTC.
- kaggle-improve stopped on 2026-10-28 by its own rule (any unsubmitted queued tag = stop) although S14 and S15
  were two days ahead: no improvement work that day. Rule changed: stop only with >= 2 unsubmitted queued tags,
  and always build on the newest queued tag (the S12 = 0.17 line).
- kaggle-loop now runs hourly 18:07-00:07 local and every 4 h otherwise. Scheduled sessions start with the task's
  stored permission mode (not the folder's bypassPermissions), so an unlisted command waits for a human: Emanuele
  approved (2026-10-29) an allowlist in Hackaton/.claude/settings.local.json for the tasks' commands (python tools/*,
  -m analysis.*, -m pytest, kernels/* builders, -m kaggle kernels/competitions, git status/pull/add/commit/push/log/
  diff, Edit of gemma4-swe-agent/**). Emanuele: PC and app stay on in the evening; GPU quota 30 h/week, next reset
  ~2026-10-31 11:30 UTC.

## Kaggle authentication (verified 2026-10-28 23:39 UTC)
- The CLI's OAuth login (~/.kaggle/credentials.json) lasts ~12 h and is not refreshed automatically: written
  2026-10-26 18:22 UTC -> "Authentication required" from ~06:30 UTC; written 2026-10-28 11:27 UTC -> failing at
  23:36 UTC. Unattended runs then stop at status.py. Durable fix needs Emanuele (tokens are never handled by the
  assistant): a non-expiring API token from kaggle.com/settings/api saved as ~/.kaggle/access_token (and, if the
  expired OAuth file still takes precedence, a CLI logout). Until then the loop needs a fresh login every 12 h.

## Release process (owner decision 2026-10-27, replaces the policy below where they differ)
Emanuele (chat, 2026-10-27): "if you submit S12 today, submit S14 tomorrow"; every UTC day a NEW version that fixes
the previous failures, even without a GPU dev panel. Mechanism (all in code, not only in instructions):
- submit_queue.json: ordered versions to ship; tools/submit_next.py submits the first one not in runs.csv when no
  submission is pending and none was made today (kaggle-loop step 5).
- tools/release_gate.py: a tag with its own dev panel ships only if that panel passes SANITY (>= 20 tasks finished,
  resolved_on_solvable >= 4, 120 x mean task time <= 11 h, editor never missing after localize); a tag without a
  panel needs candidates/<TAG>/GATE.json: same zip sha, official compile, base tag passed panel SANITY,
  agent.yaml/eval_config/sampling byte-identical to the base (time profile measured), skill files equal to a fully
  passing harness-sandbox check (kernels/editor_check records their sha256 from v8), prompt diff <= 6 lines unless
  allowed explicitly, agent/ == candidate and both test suites passing. tools/kaggle_submit.py enforces it again;
  only --owner-exception "<quote>" overrides, and it is logged in runs.csv.
- kaggle-improve (daily 12:20 local): one verified fix per day, frozen, gated (or panel-tested when GPU quota
  exists), appended to submit_queue.json. If no verifiable fix exists it reports instead of queueing noise.
- GPU quota: 0 until ~2026-10-31 11:30 UTC (Emanuele, 2026-10-27: 2:30 h left, reset in 85 h; S13 used ~1.6 h).
- Queue now: S12 (tonight, own panel 13/24), S14 (2026-10-28, gate passed), S15 (2026-10-29, gate passed).

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
| Queue | 2026-10-28 23:25 UTC: public scores S1 0.15, S3 0.12, S5 0.12, S12 0.17 (best so far, 10/58); S14 SUBMITTED 23:23 UTC (PENDING); S15 next in submit_queue.json (2026-10-29 slot) |
| S4 (16a19a7ecd46) | panel done 2026-10-14 07:15 UTC: 5/22 resolved (best so far), 9 timeouts, empty 3, no_edit 2, BUT tasks_with_arg_errors 3 -> 8 (arg_errors 5 -> 43, 42 backtick) -> BLOCKED by rule; needs fix (new tag) |
| S5 (39038672b64d) | submitted 2026-10-26 20:50 UTC, COMPLETE, public score 0.12 (seen 2026-10-27 21:32 UTC); panel done 2026-10-26 20:34 UTC: 5/21 resolved, 12 timeouts, empty 10, no_edit 8, tasks_with_arg_errors 1 (arg_errors 4) -> BLOCKED (empty + no_edit 18 vs 5) |
| S6 (291a2befe7e9) | panel done 2026-10-26 22:41 UTC: 5/22, editor not reachable in 15 tasks -> BLOCKED (infrastructure); superseded by S7 |
| S7 (d45ce6480567) | panel done 2026-10-27 01:35 UTC: 7/22 resolved (best so far; first resolves of rich_3063, rich_3471, rich_3506; lost rich_3777, resolved in S4-S6), timeouts 8, empty 6, no_edit 6, arg_errors 1; editor applied in 18 tasks, editor_not_applied 5/33, editor_missing 1 (rich_4070: the model called the editor before localize, then followed the recovery rule, ran localize and edited). Rule: SANITY fails as written (editor_missing = 0 required; the one miss is model ordering, not infrastructure); READY criteria also fail (tasks with a malformed edit attempt 4 > 1, counting EDIT NOT APPLIED; empty + no_edit 12 > 7) -> BLOCKED. Not submitted unless Emanuele grants an explicit exception |
| S8 (e8978829045f) | panel done 2026-10-27 04:08 UTC: 5/21 resolved (rich_3782 gold failed this run), timeouts 7, empty 4, no_edit 4, arg_errors 1; first edit median 238 s (S7 135 s); editor_missing 4 (rich_3944 x3, rich_4070 x2, both without a localize call first); mean task 350 s -> 11.68 h for 120 tasks. BLOCKED by its SANITY rule (time and editor_missing); READY also fails (5 < S7's 7) |
| B1 (240d785b6daa) | baseline panel done 2026-10-27 06:10 UTC: 6/21 resolved (rich_3772 resolved for the first time by any run), timeouts 3, empty 5, no_edit 2, first edit median 93 s, arg_errors 57 in 625 calls (edit_file backticks, as in S1-S5), mean task 277 s -> 9.2 h for 120 tasks |
| S9 (dc9e4d329ec5) | mixed panel done 2026-10-27 ~08:00 UTC: 12/24 resolved (fastapi 9/12, rich 3/12; S7/S8/B1 on the same 12 rich: 5/3/3), timeouts 4, empty 4, no_edit 3, arg_errors 2, first edit median 96 s, mean task 209 s -> 7.0 h for 120 tasks; editor_missing 6: rich_3905 x3 and rich_4070 x2 before any localize call, rich_3067 x4 AFTER localize: localize's 'No symbol matches the query' path returned before installing the editor (our bug, present since S6; the model recovered and resolved 3067). Rule: SANITY fails as written (infrastructure) -> BLOCKED; fixed in S11 (S9 + fix) and S12 (S10 + fix) |
| S11 (d170eeca0ee1) | frozen 2026-10-27 08:10 UTC: S9 with localize installing the editor on every exit path (regression test added); no panel of its own (GPU quota) -> submit only on Emanuele's explicit exception |
| S12 (cb8fcafd455f) | mixed panel done 2026-10-27 10:08 UTC: 13/24 resolved (fastapi 9/12, rich 4/12; S9 12/24 on the same tasks, differing only on rich_3506), timeouts 3, empty 3, no_edit 1, arg_errors 0 in 480 calls, editor not applied 6/48, editor missing 3 before any localize call and 0 after, first edit median 149 s, mean task 257 s -> 8.57 h for 120 tasks. Rule: SANITY PASSED; READY (13 >= S9's 12, fastapi 9 >= 9). SUBMITTED 2026-10-27 21:33 UTC (kernel v4), PENDING; packager printed worst_case_hours 17.25 (nominal bound; panel measured 8.57 h) |
| Paper | 2026-10-26: 4.10 rewritten from the pooled S1-S4 failure audit (results/failure_audit.json -> agent_summary "failure"): 59.3% rank-1 edited file, >= half of unresolved runs edited a gold file, edit_file 73/208 vs run_command 0/807 malformed; abstract agent sentence; SweRank (Reddy et al., ICLR 2026, arXiv 2505.07849, verified) in related work; compact table + paper/RESULTS_AGENT.md; build now fails above 3,000 words (2,968 now, room for ~2 more tag rows); 93 claim guards pass. Refresh: python -m analysis.failure_audit && python tools/agent_summary.py && python -m locstudy report |

## Submission queue (when nothing is pending, kaggle-loop submits the READY entry with the most panel resolves, newest on ties)
Candidates are frozen in candidates/<TAG>/ (bundle + sha); submissions always use the frozen copy (tools/kaggle_submit.py).
| Tag | Status | Change vs previous | Hypothesis |
|---|---|---|---|
| S2 | SKIPPED (superseded by S3 on 2026-10-13: tie on resolves, newest wins; S3 fewer timeouts) (panel: resolved 4/21 = S1; tasks with malformed calls 14 -> 5; timeouts 16 -> 14; empty patches 7 -> 9; no_edit 5 = 5) | backtick-free prompt/outputs, <=3 reads before edit, edit by call 6, 32-call cap | malformed calls and over-exploration cause most S1 timeouts |
| S3 | SUBMITTED 2026-10-13 (panel: resolved_on_solvable 4/22; timeouts 12; empty_patch 7; tasks_with_arg_errors 3; no_edit 5; timeouts+no_edit 17 vs S2 19 -> READY) | S2 + localize shows rank-1 source in anchored mode (edit without a read), write_file /tmp misuse explained, finalize deletes /workspace/tmp | S2 traces: 10-24 reads per task and first edit at 122 s median dominate the 14 timeouts |
| B1 | PANEL DONE 2026-10-27 06:10 UTC: 6/21 (BASELINE, never submit: public Budget-Fit by verracodeguacas, Apache 2.0, files extracted verbatim from its notebook; zip build/baselines/B1.zip sha 240d785b6daa, built with kernels/agent_eval/build.py --tag B1 --zip build/baselines/B1.zip) | reference point: the most replicated public configuration (~10/58 public tasks over ten draws) on our 24-task panel, so S8+ can be compared task by task with it | measures whether our skills add anything over a pure prompt at the same budget |
| S16 | GATE PASSED 2026-10-29 ~00:00 UTC, queued after S15 (sha 19922aedd503; base S12) | S15 + 2 prompt lines: a grep/git grep with no match returns status error with empty output and only means no match; close each editor heredoc with exactly one EOF | S9/S12/S13 traces: 165 run_command errors of 697 calls, 63 of them empty no-match searches (grep 46, git grep 17); 6 successful edits reported as exit 127 because a second EOF line ran as a command. Effect on score not measurable without GPU; removes confusion, adds no work |
| S15 | GATE PASSED 2026-10-27 15:05 UTC, queued for 2026-10-29 (sha a9049082de21; base S12) | S14 + editor backslash-count tier: when SEARCH equals the file except that every backslash run in the file is the same multiple k of the run typed, apply it and scale the replacement's runs by k; a run that cannot be scaled refuses the edit | S7-S13 NOT APPLIED with similarity >= 0.95: 9 of 16 are backslash-count only (rich_3535 x4, rich_3063, fastapi_15588 x4; S13 fastapi_15588 resent the same block 5 times). Verified: 55 + 36 unit tests (4 new cases), harness sandbox editor_check v9 26/26 incl. the case through the sandbox heredoc |
| S14 | SUBMITTED 2026-10-28 23:23 UTC (kernel v5, PENDING); GATE PASSED 2026-10-27 14:50 UTC (frozen 12:25 UTC, sha 0d410b080341; base S12; editor_check v8 25/25) | S12 + finalize imports every changed package module in a fresh interpreter and reports import-time errors whose traceback runs through a changed file (missing third-party packages excluded); prompt: fix any syntax or import error finalize reports, then run it again | S13 panel rich_4070: compiled patch, NameError at import, all hidden tests failed. Verified: 51 + 35 unit tests, harness sandbox kernels/editor_check v7 25/25 (results/editor_check/v7). No GPU panel: quota ~0 until 2026-10-31 ~11:30 UTC; submit only with Emanuele's explicit approval of a panel-less submission |
| S13 | BLOCKED 2026-10-27 12:10 UTC, never submit (targeted panel: 0 of S12's 11 failures fixed, controls 3/3; slower than S12 on the same 14 tasks, 346 s vs 299 s mean, empty patches 5 vs 2; rule needed >= 2 fixes) (frozen 2026-10-27 10:30 UTC, sha b3338d9192d9; panel pushed 10:33 UTC; TARGETED panel kernel: S12's 11 failures + 3 S12-resolved controls, build.py --tasks ...) | S12 + verify step: check the issue's behaviour through the public API with the issue's example (FastAPI TestClient app, rich Console(file=StringIO) render, requests public call) and assert exact values, messages and edge cases, instead of testing one's own helper; panel per_task now records the hidden-test output tail | S12 failures: fastapi_13920 edited helpers in _compat and verified them with its own scripts (gold: dependencies/utils.py), fastapi_15588 checked \n only with its own message (gold: \r and \n, 'must be a single line'), rich_3535/3471 self-checks; Google BRT evidence for reproduction checks |
| S12 | SUBMITTED 2026-10-27 21:33 UTC (tools/submit_next.py, gate OK; kernel v4) (was READY 2026-10-27 10:15 UTC, SANITY PASSED (mixed panel 13/24: fastapi 9/12, rich 4/12; 8.57 h; editor missing after localize 0) (frozen 2026-10-27 08:10 UTC, sha cb8fcafd455f; mixed panel kernel v11 pushed 08:11 UTC) | S10 + localize installs the editor on every exit path | as S10; rule: 'Decision rule for S12' |
| S11 | FROZEN, no panel (frozen 2026-10-27 08:10 UTC, sha d170eeca0ee1) | S9 + localize installs the editor on every exit path | S9's mixed panel 12/24; owner-approved fallback if S12 fails SANITY (EXCEPTION APPROVED line) |
| S10 | SUPERSEDED by S12 2026-10-27 08:10 UTC, never run, never submit (has the localize no-match bug) (frozen 2026-10-27 06:55 UTC, sha 005c6be6738c) | the public Budget-Aware V10 prompt (Flexonafft, Apache 2.0, via prvsiyan's 0.20 reproduction; see NOTICE) with edit_file/write_file replaced by our heredoc editor, localize as call 1, finalize before submit_patch, no backticks; V10 budget and sampling (8 min, 28 calls, 80 turns, 240 s; temperature 0.2, thinking 4,096) | that prompt family scores 0.18-0.22 in single public draws (mean ~10/58) vs our S1 0.15 and S3 0.12, and loses calls to edit_file argument errors (B1: 57 of 625), which our editor removes (S7: 1 of 537) |
| S9 | BLOCKED 2026-10-27 08:15 UTC, never submit (SANITY: editor missing after localize in rich_3067, localize no-match bug; mixed panel 12/24, fastapi 9/12; superseded by S11) (frozen 2026-10-27 06:10 UTC, sha dc9e4d329ec5; mixed panel kernel v10) | S7 + timeout_seconds 240 (hidden-test timeout only) + Budget-Fit's call-numbered BUDGET section in the prompt (about 10 calls to find and read, an edit by the 12th call, no new exploration after the 20th), replacing S7's bracket limits (3 reads, edit by the 6th call) | pre-registered choice (a): B1 empty + no_edit 7 vs S7 12. Our data: gold-solvable sessions whose first edit comes after the 12th counted call or never resolve 8/87 (9%), earlier ones 37/106 (35%), S1-S8 + B1 |
| S8 | BLOCKED 2026-10-27 04:20 UTC, never submit (SANITY: 120 x mean task time 11.68 h > 11.0 h; editor_missing 4; panel 5/21) (frozen 2026-10-27, sha e8978829045f) | S7 + the scorer-proven public Budget-Fit budget and sampling: 8 min, 28 calls, 80 turns, 240 s commands, temperature 0.2, thinking 4,096; prompt says 8 minutes and drops the S4 think-briefly rule | the 5-minute cap was self-imposed from an unverified rule (overrun = whole run fails; 120 x cap); Budget-Fit with this budget averages ~10/58 public tasks over ten draws (dmitriigluzdov ideas-and-evidence notebook) vs our 9 and 7, and a public author lowering these limits fell to 0.13 |
| S7 | BLOCKED 2026-10-27 01:45 UTC (SANITY as written: editor_missing 1; panel 7/22, best so far; see the S7 panel row) (frozen 2026-10-26 23:41 UTC, sha d45ce6480567; panel kernel v7 pushed 23:41 UTC) | S6 + editor installed in <workspace>/.git/swe and called as python3 /workspace/.git/swe/edit.py; edit.py maps the sandbox's real tmp/workspace/bin paths in edit text back to /tmp, /workspace, /usr/local/bin. Verified in the harness's own SubprocessManager + AdkSandboxCodeExecutor: kernels/editor_check v6 23/23 | same as S6, now actually testable: one code value per call (heredoc editor) removes the malformed-edit failure class (edit_file 77/248 malformed over S1-S6, run_command 0/1,047) |
| S6 | BLOCKED 2026-10-26 23:30 UTC, fails the SANITY gate (infrastructure): editor not found by run_command in 15 tasks (36 of 52 editor calls: python3 can't open file; the harness's subprocess sandbox rewrites /tmp in run_command strings, while localize installed into the real /tmp). Panel 5/22 resolved, timeouts 12, empty_patch 12, no_edit 7; failure_audit NO_EDIT_TOOL 5, NO_EDIT 10; editor applied in only 3 tasks; arg errors 1. The hypothesis was not tested: S7 repeats it with the path fixed. Never submit S6 | S5 minus edit_file, write_file and replace_lines.py; plus skill script edit.py, installed by localize.py (and by finalize.py on an empty patch) to /tmp/swe/edit.py and called from run_command with the code in a quoted heredoc: SEARCH/REPLACE blocks (exact, whitespace, indentation and copied-line-number tiers; unique match; all-or-nothing; compile guard; atomic write keeping EOL/mode; idempotent via a journal in .git), line ranges, new files; an unquoted heredoc is recovered raw from /proc | the gemma4 call parser emits keys alphabetically, so edit_file's long new_string precedes old_string and a stray closing backtick swallows old_string: edit_file 73/208 calls malformed in S1-S4 (S4 41/78; 2 solvable tasks lost with no edit, NO_EDIT_TOOL), run_command 0/807 (incl. 177 python -c, 26 heredocs). One code value per call removes the failure class |
| S5 | SUBMITTED 2026-10-26 20:50 UTC (Kaggle 57678289, daily-submission policy; panel rule had said BLOCKED at 20:36 UTC: panel: resolved_on_solvable 5/21; timeouts 12; empty_patch 10; no_edit 8; tasks_with_arg_errors 1 (arg_errors 4 vs S4 43); failure_audit: NO_EDIT 10, WRONG_FILE 1, RIGHT_FILE_TIMEOUT 2, RIGHT_FILE_WRONG_FIX 3, NO_EDIT_TOOL 0; replace_lines never called. Rule: empty_patch + no_edit 18 vs S4 3 + 2 grows by more than 2 = new failure mode -> BLOCKED. Malformed calls fixed, but 10 sessions never edited) | S4 + skill script replace_lines.py (write_file the new lines to tmp_new_lines.txt, then replace lines A-B by number; refuses a result that does not compile) + prompt rule: after a missing-parameter or twice-not-found edit_file error never resend edit_file for that change, use the line fallback | S4 traces: 41/78 edit_file calls lost old_string in the call serialization (7 tasks), resent unchanged up to 13 times (identical_repeat 29); write_file (one code value) lost a field only 4 times in 76 across S1-S4 |
| S4 | BLOCKED 2026-10-14 (panel: resolved_on_solvable 5/22; timeouts 9; empty_patch 3; tasks_with_arg_errors 8 vs S3 3 (arg_errors 43, backtick 42 vs 5); no_edit 2; empty+no_edit 5 vs 12 ok, but more arg errors = new failure mode per rule) | S3 + thinking_budget 2048 -> 1024, prompt rule: think briefly, edit the most plausible option and let the check decide | capped 2,048-token thinking turns (~60 s each, 28-29% of agent time in S1-S3) cause the late/no edits behind 7 empty patches and 12 timeouts |

Decision rule for S13 (written 2026-10-27 10:32 UTC, before its targeted panel of 14 tasks: S12's 11 unresolved
gold-solvable mixed-panel tasks + 3 S12-resolved controls fastapi_5077, fastapi_14794, rich_3882). Caveat: tasks
selected for failing once can pass on a rerun by chance (S9 and S12 agreed on 23 of 24 tasks, so this is modest).
SANITY: >= 12 of 14 finished, 120 x mean task time <= 11.0 h (conservative here: failures run longer), editor
missing after localize = 0. S13 replaces S12 as the next submission (2026-10-28 slot) if SANITY passes, it resolves
>= 2 of the 11 S12 failures and >= 2 of the 3 controls; otherwise the next slot gets the best other SANITY-passing
never-submitted tag (none today besides S12, which goes first).
EXCEPTION APPROVED by Emanuele in chat, 2026-10-27 ~08:20 UTC: if S12 fails its SANITY gate, submit S11 (S9 +
localize fix, no panel of its own) at the next free slot. Scope: S11 only, this one decision; it does not relax any
other rule. GPU quota left at that time: 5 h (Emanuele, from kaggle.com settings; S12 panel running).
Decision rule for S12 (written 2026-10-27 08:15 UTC, before its panel): S10's rule unchanged, with S9's mixed-panel
result (12/24, fastapi 9/12) as the comparison. If S12 passes SANITY it is the next submission; else the candidate
is S11 (S9 + the one-path localize fix), which has no panel of its own and needs Emanuele's explicit exception.
Decision rule for S10 after its panel (written 2026-10-27 06:55 UTC, before the panel; same mixed panel as S9):
SANITY as for S9 (>= 20 tasks finished, 120 x mean task time <= 11.0 h, resolved_on_solvable >= 4, no editor
"No such file" after a localize call). Submission order under the daily policy: among SANITY-passing never-
submitted tags, the higher resolved_on_solvable on this mixed panel, S10 on a tie (newest). READY (final selection
and paper only): resolved_on_solvable >= S9's, and fastapi-12 resolved >= S9's.
Decision rule for S9 after its panel (written 2026-10-27 06:15 UTC, before the panel). Panel: mixed, 12 rich tasks
from the 21 gold-solvable in both S7 and S8 + 12 fastapi tasks from the 31 gold-solvable in kernels/gold_check
(build.py --mix Textualize/rich=12 fastapi/fastapi=12 --pools results/gold_check/pools.json, seed 0 per repository).
On the same 12 rich tasks: S7 5, S8 3, B1 3 resolved; S7 empty + no_edit 2. SANITY: finished on >= 20 tasks,
120 x mean task time <= 11.0 h, resolved_on_solvable >= 4, no infrastructure failure (editor "No such file" after a
localize call in the same session = 0; a miss before any localize call is model ordering and is reported, not
counted). A SANITY-passing S9 is submitted when S5 has scored (daily policy). READY (final selection and paper
only): rich-12 resolved >= 4 and fastapi-12 resolved >= 3, and the hypothesis check: the share of gold-solvable
sessions whose first edit comes after the 12th counted call or never is <= 40% (pooled S1-S8 + B1: 87/193 = 45%).
S9 choice (pre-registered 2026-10-27 02:10 UTC, before the S8 and B1 panels; one change on top of S8):
(a) if B1's empty_patch + no_edit is at least 3 below S8's, S9 = S8 + Budget-Fit's call-numbered deadlines (its
"Budget" section: about 10 calls to find and read, an edit by the 12th call, no new exploration after the 20th),
with edit_file replaced by our editor; (b) else if S8's RIGHT_FILE_WRONG_FIX + WRONG_FILE >= its NO_EDIT, S9 = S8 +
reproduce-first (run the issue's example before and after the edit); (c) else S9 = S8 + localize printing the
rank-1 enclosing function in full and an elapsed-time line from the session's first localize call. Evidence for the
rule: S7 resolved tasks read 1-3 times before the first edit, NO_EDIT sessions 7-22 (median window 34 lines, 42 of
220 reads mostly re-read lines already shown); turns are short (median 75-340 completion tokens), so those sessions
end on the call cap, not the clock.
Amendment 2026-10-27 04:40 UTC (after S8, before B1's results): S8 failed its time check, so S9's base is S7 (best
panel, 8.6 h for 120 tasks) plus timeout_seconds 240, which here changes only the hidden-test timeout (no agent
command reached 100 s in S7 or S8: 0 command timeouts in 1,081 calls). The (a)/(b)/(c) choice is unchanged, with S7
in place of S8 (S7: empty_patch + no_edit = 12; RIGHT_FILE_WRONG_FIX + WRONG_FILE = 5 vs NO_EDIT 7).
Decision rule for S8 after its panel (written 2026-10-27 before the panel): SANITY: editor_missing = 0, panel finished
on >= 20 tasks, and 120 x mean per-task duration_s <= 11.0 h (duration_s includes hidden-test verification, which the
scorer's 12 h excludes, so this is conservative); a failed time check means BLOCKED and never submitted. READY if
resolved_on_solvable >= S7's and >= 5, NO_EDIT_TOOL = 0 and empty_patch + no_edit <= 7; otherwise BLOCKED.
Decision rule for S7 after its panel (written 2026-10-26 23:45 UTC, before the panel): SANITY first:
editor_missing = 0 and at least one editor call applied in >= 15 of the tasks that edit (else infrastructure
failure, never submit). READY if resolved_on_solvable >= 5 (best panel so far: S4, S5, S6 = 5), tasks with a
malformed edit attempt <= 1, editor_not_applied / editor_calls <= 0.35, NO_EDIT_TOOL = 0 and empty_patch + no_edit
<= 7 (S4: 3 + 2, plus 2); otherwise BLOCKED. Under the daily policy a SANITY-passing S7 is submitted when the slot
frees whatever its READY/BLOCKED verdict, which then only feeds the final selection and the paper.
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

## Findings S13 (targeted panel, 2026-10-27; first panel with hidden-test output recorded)
- The public-API verification rule fixed none of S12's 11 failures and cost time (346 s vs 299 s mean on the same
  14 tasks, empty patches 5 vs 2): dropped.
- Hidden-test output (new in per_task.jsonl) names the failures: fastapi_13920 422 != 200 (fix in the wrong
  place); fastapi_15588 exact message "SSE 'id' must be a single line" expected; rich_3535 regex range still wrong;
  rich_3675 test expects isatty() to be called; rich_3930 needs a new module (rich._unicode_data, CellSpan);
  rich_4070 the patch compiled but broke the import (removed import inspect, still used in a class body:
  NameError) -> every hidden test failed. finalize only compiled; S14 adds an import check.

## Findings S9 (first mixed panel, 2026-10-27)
- fastapi is far more solvable for this agent than rich: 9/12 vs 3/12 on gold-solvable tasks. fastapi statements
  are long PR descriptions (median 677 chars, code examples) while rich's are PR titles (median 138); fastapi
  patches touch fastapi/ core (51 of 67), 15 also docs_src/. The rich-only panel (S1-S8) underestimated the
  hidden-set rate, whose local sample is 52% fastapi.
- The call-numbered BUDGET section moved the first edit earlier (median 96 s vs S7 135 s) and sessions shorter
  (209 s mean vs 257 s), 7.0 h estimated for 120 tasks.
- Bug found: localize returned before installing the editor when no symbol matched the query (rich_3067); fixed
  with try/finally around the whole run plus a regression test.

## Findings leaderboard (kaggle.com, read 2026-10-27 06:40 UTC)
- Public leaderboard = ~50% of the test data; prizes use the other 50% (private). 3,884 teams; 5 at 0.24 (14/58),
  40+ at 0.22 (13/58). Public notebooks: best single draws 0.22 (Budget-Aware v2), 0.20 (Shape of Doubt = V10
  reproduction, SuperAgent reproduction), many 0.18. Consistent with configurations of mean ~10/58 (sd ~2.9 tasks per
  draw) submitted daily: the top public scores are best-of-many draws.
- So the public goal ">= 11/58" needs a mean of ~10-11 plus daily draws; 13-14 needs a mean near 12 or luck. The
  private ranking rewards the mean, not the best draw.

## Findings B1 (Budget-Fit verbatim on the rich panel, 2026-10-27)
- 6/21 resolved vs S7 7/22 and S8 5/21: within one run's noise of our best. Our skills do not show a measurable gain
  over the public prompt on this panel; the honest reading is "comparable", not "better".
- B1 edits early (first edit median 93 s; S7 135 s, S8 238 s) and ends sessions early (mean 277 s with an 8-minute
  cap; S8 350 s), which is why its budget fits 12 h. It still loses 57 calls to edit_file argument errors.
- Panel-to-leaderboard anchor: B1's configuration averages ~10/58 public tasks over ten draws; B1 here 6/21.

## Findings gold check (kernels/gold_check v1, CPU, 2026-10-27 05:00 UTC; results/gold_check/summary.json)
- The 2026-10-12 note "fastapi gold fails: pydantic cannot import" no longer holds: fastapi gold patches resolve in
  31 of 67 tasks in the same subprocess sandbox (kernel python 3.12.13; data/wheels has pydantic 1.10.15 and 2.13.4,
  pydantic_core 2.46.4 cp312 and cp313). The other 34 + 2 fail at collection on missing test-only modules (e.g.
  dirty_equals), an environment gap of this kernel, not of the patches. requests: 1 of 13 (httpbin fixtures need
  the network); one requests test file runs 72 s, close to the old 100 s hidden-test timeout. httpx: 0 of 1.
- results/gold_check/pools.json: 31 gold-solvable fastapi tasks + the 21 rich panel tasks whose gold passed in both
  S7 and S8. kernels/agent_eval/build.py --mix Textualize/rich=12 fastapi/fastapi=12 --pools results/gold_check/pools.json
  builds a mixed panel (each repository sampled with its own seed).

## Findings S8 (dev panel 2026-10-27; 21 gold-solvable, 5 resolved)
- More time did not buy resolves: the first edit moved from 135 s (S7 median) to 238 s, so sessions spent the extra
  three minutes exploring. 7 sessions ran to the 8-minute cap (S7: 11 to the 5-minute cap).
- thinking_budget 4096 lengthens some turns badly: rich_3521 median turn 117 s (2,256 completion tokens), 6 counted
  calls in 482 s, no edit.
- 120 x mean task time = 11.68 h: the Budget-Fit budget is proven for Budget-Fit's prompt (it submits in ~8-10
  turns), not for an agent that uses the whole cap.
- Panel noise: S4-S8 resolve 5, 5, 5, 7, 5 of 21-22; 8 distinct tasks over S1-S8, the other 14 never. With p ~ 0.3 and
  n = 22 one run has a binomial sd of ~2.1 tasks, so S7 vs S8 (7 vs 5) does not separate the configurations, and the
  thresholds of 5 in the READY rules sit inside that noise. Comparisons need the union/intersection of resolved sets,
  repeated runs, or a larger panel.
- Coverage: the panel is rich-only because fastapi gold patches failed in this kernel on 2026-10-12 ("pydantic cannot
  import", cause never recorded); the local task list is 67 fastapi, 48 rich, 13 requests, 1 httpx. kernels/gold_check
  (CPU, no quota) reruns the gold phase on all non-rich tasks with diagnostics to find the cause.

## Findings S7 (dev panel 2026-10-27; 22 gold-solvable, 7 resolved)
- The editor works where it is reachable: applied in 18 tasks, 5 of 33 calls NOT APPLIED, 0 unquoted heredocs,
  1 arg error in 537 calls. Resolved 7 (S4-S6: 5); 8 distinct tasks resolved over S1-S7.
- Counted calls: run_command and read_file (swegemma tools @budget_gated) and skill script runs (the code executor
  calls context.check_budget() with the default count_tool_call=True) count; submit_patch and get_status do not
  (count_tool_call=False). Rejected calls still appear in traces. 4 tasks got "Tool call budget exhausted
  (32 calls)": rich_3469 (gold-unsolvable), rich_3472, rich_3777, rich_3938, the last three without a source edit
  (3777 was resolved in S4-S6). S8's 28-call cap stops such sessions earlier: S8 tests the time and test-timeout
  gain against that loss as frozen (one change set, the public proven budget).
- Two resolves land at 305 s (rich_3471, rich_3506), at the 5-minute cap; 4 NO_EDIT sessions are time-capped with
  18-25 counted calls (slow turns, not many calls).
- 120 x mean task time 8.6 h at the 5-minute cap (duration_s includes hidden-test verification).

## Findings 2026-10-27 (public notebooks + harness code)
- swegemma verification.py runs the hidden tests with timeout = eval_config timeout_seconds. S1-S7 used 100 s: a hidden
  test file slower than 100 s fails a correct patch (public Budget-Fit notes ~100 s for requests' test files). Our rich
  panel could not show it (gold test runs take 2-3 s). S8 uses 240 s, the scorer-proven value.
- Public run-to-run spread with identical files: 7, 7, 9, 11, 13 of 58 (budget-aware v2), Budget-Fit mean ~10/58 over
  ten draws; the 0.24 top scores (14/58) are high draws of these configurations. A 12B variant exceeded 12 h (no score).

## Findings S6 (dev panel 2026-10-26; 22 gold-solvable, 5 resolved) - infrastructure failure
- The harness runs tasks in SubprocessManager sandboxes (swegemma/sandbox/subprocess.py): run_command rewrites
  /tmp, /workspace, /usr/local/bin and /wheels inside the WHOLE command string (heredoc included) to the task's
  sandbox directories. Skill scripts run as Python files (adk_eval_core AdkSandboxCodeExecutor), so their string
  literals are not rewritten: localize installed the editor into the real /tmp/swe while run_command looked in
  <sandbox>/tmp/swe. 36 of 52 editor calls failed with "can't open file" (15 tasks); the model found the real path
  with find in 3 tasks; the other resolved tasks edited with python -c/sed.
- The bash-only Linux check could not see it (no path rewriting there). Lesson: check scripts in the harness's own
  sandbox classes, not in an imitation of them (kernels/editor_check part B, from v3).
- Second consequence of the same rewriting, fixed in S7: code inside a heredoc that names /tmp, /workspace or
  /usr/local/bin would be written with the sandbox's real paths; the editor now maps them back.

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
