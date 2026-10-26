---
name: swe
description: Fast issue localization (ranked symbols with file:line ranges, signatures and related tests), a SEARCH/REPLACE file editor driven from run_command, and patch hygiene before submit_patch.
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
line ranges. Optional: args {"query": "...", "k": 40} for a longer list. It also installs the editor.

## the editor: how to change files
Call run_command with the code in a quoted heredoc, each marker on its own line:

python3 /tmp/swe/edit.py path/to/module.py <<'EOF'
<<<<<<< SEARCH
exact current lines, copied from read_file
=======
replacement lines
>>>>>>> REPLACE
EOF

Several blocks for the same file may follow each other in one call; they apply in order, all or nothing. Other
forms: python3 /tmp/swe/edit.py path/to/module.py 120-125 followed by the same heredoc holding only the new lines
replaces lines 120 to 125 (120-119 inserts before line 120); a path that does not exist yet creates that file
with the heredoc as its content. A SEARCH that is missing or not unique, or a result that would not compile,
changes nothing and prints the closest lines with their numbers. Applied edits print the new region.

## scripts/finalize.py: before submit_patch
run_skill_script with skill_name swe and file_path scripts/finalize.py.

Reverts edits to tests and test configuration, deletes scratch files left in the workspace, compiles every changed
Python file and prints the diff stat. Fix any reported syntax error, then call submit_patch.
