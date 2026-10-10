#!/usr/bin/env bash
# One-command reproduction of every table, figure and number in paper/PAPER.md.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest -q tests/test_locstudy.py          # unit tests on synthetic fixtures
[ -s data/tasks.jsonl ] || bash scripts/fetch_data.sh   # dev subset (needs a Kaggle API token)
python -m locstudy run                              # per-task outcomes + summary with CIs and paired tests
python -m locstudy sensitivity                      # one-at-a-time robustness grid
python -I -c "import sys;sys.path.insert(0,'.');from pathlib import Path;from locstudy import audit;audit.run(Path('data'),Path('results'))"
python -m locstudy report                           # RESULTS.md, figures/, PAPER.md (template filled from results)
