# Plan (≈ 8 h/week alongside PRAXI + university)

| Week | Dates (2026) | Goal | Exit criterion |
|---|---|---|---|
| 1 | 10–16 Oct | Join, read harness docs, run a sample task locally, E0 submission | First leaderboard score |
| 2 | 17–23 Oct | E1 dense-retrieval skill + localization logging (gold files from validation tasks) | Recall@k table E0 vs E1 |
| 3 | 24–30 Oct | E2 graph expansion + E3 re-rank | Ablation table E0–E3 |
| 4 | 31 Oct–6 Nov | E4 repair sub-agent; paper figures | Best config chosen |
| 5 | 7–12 Nov | **Paper** writing (≤3,000 words) + public notebook | Paper submitted 12 Nov 23:59 UTC |
| 6–7 | 13–25 Nov | Error analysis on failures, budget tuning; entry deadline 25 Nov | Stable improvement over E3 |
| 8 | 26 Nov–2 Dec | Final 2 submissions selected | Done 2 Dec 23:59 UTC |

Rules of engagement: one daily submission is precious → every submission maps to one experiment ID with a hypothesis written before it runs. Log every run in `runs.csv` (date, ID, config hash, public score, notes).
