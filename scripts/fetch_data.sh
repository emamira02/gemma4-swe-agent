#!/usr/bin/env bash
# Download the dev subset needed for localization analysis (no 21 GB snapshots), 6 files in parallel,
# priority: tasks.jsonl + sample_submission + graphs first, embeddings last. Resumable (skips existing files).
# Competition data stays in data/ (gitignored): Kaggle rules forbid redistribution.
set -uo pipefail
cd "$(dirname "$0")/.."
COMP=gemma-4-developer-agent
mkdir -p data
listing=$(mktemp)
tok=""
for _ in $(seq 1 20); do
  out=$(python -m kaggle competitions files "$COMP" --page-size 200 --csv ${tok:+--page-token "$tok"} 2>&1)
  echo "$out" | grep -v -e "^Next Page Token" -e "^name,size" >> "$listing"
  tok=$(echo "$out" | grep "^Next Page Token" | sed 's/Next Page Token = //')
  [ -z "$tok" ] && break
done
names=$(cut -d, -f1 "$listing")
{ echo "$names" | grep -E '^(tasks\.jsonl|HARNESS_README\.md)$'
  echo "$names" | grep -E '^sample_submission/'
  echo "$names" | grep -E '^graphs/'
  echo "$names" | grep -E '^embeddings/'; } > data/.queue
rm -f "$listing"
echo "queued: $(wc -l < data/.queue) files"

fetch_one() {
  f="$1"; dest="data/$(dirname "$f")"; mkdir -p "$dest"
  [ -s "data/$f" ] && exit 0
  for attempt in 1 2 3; do
    if python -m kaggle competitions download gemma-4-developer-agent -f "$f" -p "$dest" -q >/dev/null 2>&1; then
      z="$dest/$(basename "$f").zip"
      [ -f "$z" ] && python -I -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$z" "$dest" && rm -f "$z"
      exit 0
    fi
    sleep $((attempt * 3))
  done
  echo "FAILED $f"
}
export -f fetch_one
xargs -a data/.queue -P 6 -I{} bash -c 'fetch_one "$@"' _ {}
echo "done: graphs=$(ls data/graphs 2>/dev/null | wc -l) embeddings=$(ls data/embeddings 2>/dev/null | wc -l) tasks=$(test -s data/tasks.jsonl && echo yes || echo no)"
