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
| S3 (e1af59a2b337) | panel done 2026-10-13 (4/22 resolved, 12 timeouts, no_edit 5); submitted 2026-10-13 ~21:46 UTC, PENDING |
| Paper | 4.10 agent section added (results/agent_summary.json via tools/agent_summary.py); 2,984 words incl. references; refresh: `python tools/agent_summary.py && python -m locstudy report` after each new panel/score |

## Submission queue (when nothing is pending, kaggle-loop submits the READY entry with the most panel resolves, newest on ties)
Candidates are frozen in candidates/<TAG>/ (bundle + sha); submissions always use the frozen copy (tools/kaggle_submit.py).
| Tag | Status | Change vs previous | Hypothesis |
|---|---|---|---|
| S2 | SKIPPED (superseded by S3 on 2026-10-13: tie on resolves, newest wins; S3 fewer timeouts) (panel: resolved 4/21 = S1; tasks with malformed calls 14 -> 5; timeouts 16 -> 14; empty patches 7 -> 9; no_edit 5 = 5) | backtick-free prompt/outputs, <=3 reads before edit, edit by call 6, 32-call cap | malformed calls and over-exploration cause most S1 timeouts |
| S3 | SUBMITTED 2026-10-13 (panel: resolved_on_solvable 4/22; timeouts 12; empty_patch 7; tasks_with_arg_errors 3; no_edit 5; timeouts+no_edit 17 vs S2 19 -> READY) | S2 + localize shows rank-1 source in anchored mode (edit without a read), write_file /tmp misuse explained, finalize deletes /workspace/tmp | S2 traces: 10-24 reads per task and first edit at 122 s median dominate the 14 timeouts |

Decision rule for S3 after its panel: READY if resolved_on_solvable >= 4 and timeouts + no_edit do not grow vs S2.
Decision rule for S2 after its panel (applied 2026-10-13): READY if resolved_on_solvable >= S1's (4) and tasks_with_arg_errors drops
by at least half; otherwise fix the cause seen in the traces first (new tag), never submit a known regression.

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
