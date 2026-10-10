"""locstudy: measurement of issue-localization signals for the Gemma 4 Developer Agent benchmark.

Modules: data (tasks, graphs, manifest) -> gold (labels from reference patches) -> signals (rankers)
-> metrics (hit ranks, budgets, bootstrap CIs, paired tests) -> study (end-to-end run) -> report (tables, figures).
"""
SCHEMA_VERSION = 2
