# Agent dev-panel results (auto-generated from results/agent_summary.json)

Rebuild: python -m analysis.failure_audit && python tools/agent_summary.py && python -m locstudy report. The per-task traces stay private (they contain task text); results/failure_audit.json keeps ids and counts.

| Tag | Panel tasks (solvable) | Resolved | Timeouts | Tasks with malformed calls | Median s to first edit | Public score |
|---|---|---|---|---|---|---|
| S1 | 24 (21) | 4 | 16 | 14 | 95 | 0.15 |
| S2 | 24 (21) | 4 | 14 | 5 | 122 | not submitted |
| S3 | 24 (22) | 4 | 12 | 3 | 135 | 0.12 |
| S4 | 24 (22) | 5 | 9 | 8 | 115 | not submitted |

Pooled over S1, S2, S3, S4: 86 solvable of 96 task runs, 17 resolved; localize ranks an edited file first in 51 (59.3%).

| Unresolved category | Runs |
|---|---|
| NO_EDIT_TOOL | 4 |
| NO_EDIT | 21 |
| WRONG_FILE | 9 |
| RIGHT_FILE_TOOL | 0 |
| RIGHT_FILE_TIMEOUT | 18 |
| RIGHT_FILE_WRONG_FIX | 17 |

| Tool | Calls | Malformed | Rate |
|---|---|---|---|
| edit_file | 208 | 73 | 35.1% |
| get_status | 4 | 0 | 0.0% |
| read_file | 825 | 3 | 0.4% |
| run_command | 807 | 0 | 0.0% |
| run_skill_script | 159 | 33 | 20.8% |
| submit_patch | 47 | 0 | 0.0% |
| write_file | 76 | 4 | 5.3% |
