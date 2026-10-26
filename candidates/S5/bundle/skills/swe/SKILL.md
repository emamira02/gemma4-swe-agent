---
name: swe
description: Fast issue localization (ranked symbols with file:line ranges, signatures and related tests), a line-range edit fallback when edit_file calls break, and patch hygiene before submit_patch.
---
# swe skill

Run the scripts directly with run_skill_script; loading this file is not needed. Pass skill_name, file_path and
args as separate fields.

## scripts/localize.py: where to edit
run_skill_script with skill_name swe, file_path scripts/localize.py and args {"query": "one line: identifiers,
file paths, function or class names, options, config keys, quoted error text, a few distinctive words"}.

Output: mode (anchored = names in the query resolved to symbols; lexical = ranking by word overlap only), the top
symbols as path:first-last, symbol name, signature and docstring, the files they live in, literal matches of
quoted text, and related test files. Re-rank the list using the issue, then read_file only the best one to three
line ranges. Optional: args {"query": "...", "k": 40} for a longer list.

## scripts/replace_lines.py: when edit_file keeps failing
First write_file with filepath tmp_new_lines.txt and the replacement lines as content, then run_skill_script with
skill_name swe, file_path scripts/replace_lines.py and args {"file": "path/to/module.py", "start": A, "end": B}.
Lines A to B (1-based, inclusive) are replaced; end = start - 1 inserts before line A. A result that would not
compile is not applied. Prints the removed lines and the new region with line numbers.

## scripts/finalize.py: before submit_patch
run_skill_script with skill_name swe and file_path scripts/finalize.py.

Reverts edits to tests and test configuration, deletes scratch files left in the workspace, compiles every changed
Python file and prints the diff stat. Fix any reported syntax error, then call submit_patch.
