# Agent dev-panel results (auto-generated from results/agent_summary.json)

Rebuild: python -m analysis.failure_audit && python tools/agent_summary.py && python -m locstudy report. The per-task traces stay private (they contain task text); results/failure_audit.json keeps ids and counts.

| Tag | Panel tasks (solvable) | Resolved | Timeouts | Tasks with malformed calls | Median s to first edit | Public score |
|---|---|---|---|---|---|---|
| S1 | 24 (21) | 4 | 16 | 14 | 95 | 0.15 |
| S2 | 24 (21) | 4 | 14 | 5 | 122 | not submitted |
| S3 | 24 (22) | 4 | 12 | 3 | 135 | 0.12 |
| S4 | 24 (22) | 5 | 9 | 8 | 115 | not submitted |
| S5 | 24 (21) | 5 | 12 | 1 | 70 | not submitted |

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
