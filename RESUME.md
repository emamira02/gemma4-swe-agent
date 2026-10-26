# RESUME — Kaggle loop runbook (read this first after any interruption)

Everything long-running happens on Kaggle's servers (eval kernels, scored submissions): a reboot of this PC stops
nothing. State lives in git (`runs.csv`, `results/agent_runs/*.json`, this file) and in `STATE.json` (local).

## Automation (local scheduled tasks, Claude desktop app; run when the app is open, catch up on next launch)
- kaggle-loop (every 4 h): status sync, READY/BLOCKED decisions after a panel, submits the first READY entry.
- kaggle-improve (every 2 days, 10:20): traces -> one targeted change -> tests -> new tag -> GPU dev panel.
- kaggle-paper-final (once, 5 Nov 10:00): agent results into the paper, clean-commit rebuild, submission
  (asks Emanuele only for the final click if the website is required).

## Resume in one command
    python tools/status.py
It is idempotent: refreshes submission scores into runs.csv, downloads a finished dev-panel eval, aggregates its
traces into results/agent_runs/<tag>.json, writes STATE.json, prints the next action. Then commit and push.

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
| Queue | 2026-10-26 18:31 UTC: no pending submission, no READY entry (S4 BLOCKED); no new tag since S4 (2026-10-14), waiting for kaggle-improve |
| S4 (16a19a7ecd46) | panel done 2026-10-14 07:15 UTC: 5/22 resolved (best so far), 9 timeouts, empty 3, no_edit 2, BUT tasks_with_arg_errors 3 -> 8 (arg_errors 5 -> 43, 42 backtick) -> BLOCKED by rule; needs fix (new tag) |
| Paper | 4.10 agent section added (results/agent_summary.json via tools/agent_summary.py); 2,984 words incl. references; refresh: `python tools/agent_summary.py && python -m locstudy report` after each new panel/score |

## Submission queue (when nothing is pending, kaggle-loop submits the READY entry with the most panel resolves, newest on ties)
Candidates are frozen in candidates/<TAG>/ (bundle + sha); submissions always use the frozen copy (tools/kaggle_submit.py).
| Tag | Status | Change vs previous | Hypothesis |
|---|---|---|---|
| S2 | SKIPPED (superseded by S3 on 2026-10-13: tie on resolves, newest wins; S3 fewer timeouts) (panel: resolved 4/21 = S1; tasks with malformed calls 14 -> 5; timeouts 16 -> 14; empty patches 7 -> 9; no_edit 5 = 5) | backtick-free prompt/outputs, <=3 reads before edit, edit by call 6, 32-call cap | malformed calls and over-exploration cause most S1 timeouts |
| S3 | SUBMITTED 2026-10-13 (panel: resolved_on_solvable 4/22; timeouts 12; empty_patch 7; tasks_with_arg_errors 3; no_edit 5; timeouts+no_edit 17 vs S2 19 -> READY) | S2 + localize shows rank-1 source in anchored mode (edit without a read), write_file /tmp misuse explained, finalize deletes /workspace/tmp | S2 traces: 10-24 reads per task and first edit at 122 s median dominate the 14 timeouts |
| S4 | BLOCKED 2026-10-14 (panel: resolved_on_solvable 5/22; timeouts 9; empty_patch 3; tasks_with_arg_errors 8 vs S3 3 (arg_errors 43, backtick 42 vs 5); no_edit 2; empty+no_edit 5 vs 12 ok, but more arg errors = new failure mode per rule) | S3 + thinking_budget 2048 -> 1024, prompt rule: think briefly, edit the most plausible option and let the check decide | capped 2,048-token thinking turns (~60 s each, 28-29% of agent time in S1-S3) cause the late/no edits behind 7 empty patches and 12 timeouts |

Decision rule for S4 after its panel: READY if resolved_on_solvable >= 4 (best so far: S1/S2/S3 = 4), empty_patch + no_edit do not grow vs S3 (7 + 5)
and no new failure mode appears (e.g. more arg errors or truncated-thought turns with no tool call); otherwise BLOCKED.
Decision rule for S3 after its panel: READY if resolved_on_solvable >= 4 and timeouts + no_edit do not grow vs S2.
Decision rule for S2 after its panel (applied 2026-10-13): READY if resolved_on_solvable >= S1's (4) and tasks_with_arg_errors drops
by at least half; otherwise fix the cause seen in the traces first (new tag), never submit a known regression.

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
