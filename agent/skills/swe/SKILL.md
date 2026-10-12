---
name: swe
description: Fast issue localization (ranked symbols with file:line ranges, signatures and related tests) and patch hygiene before submit_patch.
---
# swe skill

Run the scripts directly with `run_skill_script`; loading this file is not needed.

## scripts/localize.py — where to edit
`run_skill_script(skill_name="swe", file_path="scripts/localize.py", args={"query": "<one line: identifiers, file paths, function/class names, CLI options, config keys, quoted error text, 3-8 distinctive words from the issue>"})`

Output: `mode` (anchored = names in the query resolved to symbols; lexical = ranking by word overlap only),
the top symbols as `path:first-last  Symbol.name  signature  # docstring`, the files they live in, literal
matches of quoted text, and related test files. The ranking is lexical: re-rank it yourself using the issue,
then `read_file` only the 1-3 best line ranges. Optional args: `"k": 40` for a longer list.

## scripts/finalize.py — before submit_patch
`run_skill_script(skill_name="swe", file_path="scripts/finalize.py")`

Reverts edits to tests and test configuration, deletes scratch files left in the workspace, compiles every
changed Python file and prints the diff stat. Fix any reported syntax error, then call `submit_patch`.
