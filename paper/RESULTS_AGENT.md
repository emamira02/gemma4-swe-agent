# Agent dev-panel results (auto-generated from results/agent_summary.json)

Rebuild: python -m analysis.failure_audit && python tools/agent_summary.py && python -m locstudy report. The per-task traces stay private (they contain task text); results/failure_audit.json keeps ids and counts.

| Tag | Panel tasks (solvable) | Resolved | Timeouts | Tasks with malformed calls | Median s to first edit | Public score |
|---|---|---|---|---|---|---|
| B1 | 24 (21) | 6 | 3 | 3 | 93 | not submitted |
| S1 | 24 (21) | 4 | 16 | 14 | 95 | 0.15 |
| S2 | 24 (21) | 4 | 14 | 5 | 122 | not submitted |
| S3 | 24 (22) | 4 | 12 | 3 | 135 | 0.12 |
| S4 | 24 (22) | 5 | 9 | 8 | 115 | not submitted |
| S5 | 24 (21) | 5 | 12 | 1 | 70 | 0.12 |
| S6 | 24 (22) | 5 | 12 | 1 | 128 | not submitted |
| S7 | 24 (22) | 7 | 8 | 1 | 135 | not submitted |
| S8 | 24 (21) | 5 | 7 | 1 | 238 | not submitted |
| S9 | 24 (24) | 12 | 4 | 2 | 96 | not submitted |
| S12 | 24 (24) | 13 | 3 | 0 | 149 | 0.17 |
| S13 | 14 (14) | 3 | 5 | 0 | 156 | not submitted |
| S14 | – | – | – | – | – | pending |

Pooled over S1, S2, S3, S4, S5: 107 solvable of 120 task runs, 22 resolved; localize ranks an edited file first in 62 (57.9%).

| Unresolved category | Runs |
|---|---|
| NO_EDIT_TOOL | 4 |
| NO_EDIT | 31 |
| WRONG_FILE | 10 |
| RIGHT_FILE_TOOL | 0 |
| RIGHT_FILE_TIMEOUT | 20 |
| RIGHT_FILE_WRONG_FIX | 20 |

| Tool | Calls | Malformed | Rate |
|---|---|---|---|
| edit_file | 248 | 77 | 31.0% |
| get_status | 5 | 0 | 0.0% |
| read_file | 1011 | 5 | 0.5% |
| run_command | 1047 | 0 | 0.0% |
| run_skill_script | 191 | 33 | 17.3% |
| submit_patch | 59 | 0 | 0.0% |
| write_file | 94 | 4 | 4.3% |

## Runs pooled per edit channel

| Edit channel | Tags | Panel | Resolved / solvable runs | Malformed calls | Public score |
|---|---|---|---|---|---|
| edit_file (two code arguments) | S1–S5 | rich | 22/107 | 119/2,655 (4.5%) | S1 0.15, S3 0.12, S5 0.12 |
| heredoc editor (one argument) | S7, S8, S9, S12 | fastapi+rich; rich | 37/91 | 8/2,056 (0.4%) | S12 0.17 |
| public prompt, edit_file | B1 | rich | 6/21 | 61/625 (9.8%) | not submitted |

*Excluded: S6 (editor unreachable in 15 tasks (infrastructure, fixed in S7)); S13 (targeted panel: 11 selected failures and 3 controls).*

## Outcome stability over 12 panel runs (B1, S1, S2, S3, S4, S5, S6, S7, S8, S9, S12, S13)

34 tasks have at least two runs in which the reference patch resolves (2-12 runs each): 13 always resolved, 16 never, 5 mixed (rich_3063, rich_3471, rich_3506, rich_3772, rich_3777).

| Repository | Always | Never | Mixed |
|---|---|---|---|
| fastapi | 9 | 3 | 0 |
| rich | 4 | 13 | 5 |

| Mixed panel | Repository | Resolved / solvable |
|---|---|---|
| S9 | fastapi | 9/12 |
| S9 | rich | 3/12 |
| S12 | fastapi | 9/12 |
| S12 | rich | 4/12 |
