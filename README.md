# gemma4-swe-agent (private until submission)

Entry for **Google – The Gemma 4 Developer Agent Competition** (Kaggle, host Google DeepMind) and its **paper track**.

## Verified constraints (official overview + rules, read 2026-10-09)
- Base model: `gemma-4-31b-it-qat-w4a16-ct` only; optional PEFT LoRA (`.safetensors`) per agent.
- Submission: `submission.zip` with root `agent.yaml` (Google ADK Agent Config, restricted), optional `configs/`, `prompts/`, `sub_agents/`, `adapters/`, `skills/<name>/SKILL.md` (+ sandboxed `scripts/`, `resources/`).
- Harness tools: `run_command`, `read_file`, `edit_file`, `write_file`, `submit_patch`, `get_status`, **`search_similar_code`** (pre-computed embeddings), **`get_code_neighbors`**, **`get_code_subgraph`** (call/dependency graph).
- Metric: % of issues whose patch passes validation tests (SWE-bench-like). 12 h budget for all tasks. L4x4, **no internet**.
- 1 submission/day, 2 final. Team ≤ 5. Deadlines 23:59 UTC: **paper 12 Nov · entry/merge 25 Nov · final 2 Dec 2026**.
- Winners: Apache-2.0 / OSI license + reproducible code & write-up. Competition data must **not** be redistributed → never commit it.
- No private code sharing outside the team. AI coding assistants are not prohibited by the rules.

## Harness facts that shape the design (own notes from HARNESS_README, read 2026-10-10)
- Dev set: 129 public tasks from 4 repos (fastapi, rich, requests, httpx) with reference patch + test_patch, repo snapshots (.tgz), NetworkX call/dependency graphs (node = fully-qualified symbol with source text), 256-d node embeddings (.npz). Test set ≈ 120 tasks from **private repos**, split public/private LB.
- `search_similar_code(query)` resolves `query` against **node keys/suffixes** and then ranks by cosine — no live embedder offline, so free-text issue queries don't work: retrieval must be **anchored on symbol names** (from the issue text, grep, tracebacks).
- `get_code_neighbors` resolves short names (exact → suffix → case-insensitive → substring); optional edge filter (CALLS / DEFINED_IN / IMPORTS).
- 12 h for all tasks ⇒ **≈ 6 min per task** on the hidden set; set `eval_config.yaml` budgets accordingly (default 60 min/task would starve later tasks). Context 32,768 tokens with auto-compaction; read_file ≤150 lines/10k chars; command output ≤5k chars; sandbox 4 GiB RAM / 2 vCPU, offline.
- Instruction templating: `{problem_description}`, `{hints}` from session state. Agent types: LlmAgent, SequentialAgent, ParallelAgent, LoopAgent; tools by name; AgentTool sub-agents; skills = dirs with SKILL.md (+ .py scripts).
- Verification: patch applied in a fresh container; edits to tests/conftest/pytest.ini/pyproject are reset → fix library code only. Resolved iff targeted pytest passes with valid JUnit XML.
- Local CLI: `swegemma eval --tasks tasks.jsonl --snapshots-dir snapshots --submission-dir ... --sandbox docker` (needs a served Gemma 4 model; registry also lists smaller Gemma 4 variants for local runs).

## Thesis (paper + agent)
**Revised (2026-10-10):** because embedding lookup is symbol-anchored, the localization pipeline is *lexical anchors → embedding neighbours → graph expansion → re-rank*, tuned for a ~6-minute budget.
**GPU-free paper contribution (feasible by 12 Nov):** measure on the 129 dev tasks how well each signal recovers the gold-edited symbols (from `patch`): identifier extraction from the issue, BM25 over node text, embedding neighbours of anchors, k-hop graph expansion, and their combination (Recall@k / MRR, hops needed, failure taxonomy). Ship the analysis + a reusable localization skill (candidate for *Best New Resource*).

### Original thesis
**Hybrid graph-retrieval localization**: dense `search_similar_code` → graph expansion via `get_code_neighbors`/`get_code_subgraph` → lexical confirmation (`grep`) → re-rank → patch/test/repair loop. Hypothesis: better file/function localization at fixed budget raises pass rate for a 31B quantized model more than prompt tweaks do.

## Agent (main competition) — `agent/`
Single `LlmAgent` (no sub-agents, no graph tools: public ablations show no gain from either, and the scorer's
~5 min/task budget rewards fewer, better turns). What is different is the localization step, taken from the paper:
- `skills/swe/scripts/localize.py` (stdlib, runs inside the task container in ~1 s): parses the repo with `ast`,
  ranks symbols by identifier resolution (harness-style tiers), BM25 and quoted-literal matches, fused only when
  the issue names a resolvable symbol (the paper's mode rule), and prints `path:first-last symbol signature # doc`
  plus related test files. The model then re-ranks this list itself — the paper's strongest result (re-ranking
  BM25's top 50: top-5 recall 25% → 61%).
- `skills/swe/scripts/finalize.py`: reverts protected test/config edits, deletes scratch files, compiles changed
  files, prints the diff stat — before `submit_patch`.
- `prompts/system.md`: localize → choose → read ranges → edit early → one targeted check → finalize → submit.
- `eval_config.yaml`: 5.0 min/task, 100 s per command, 40 tool calls, 60 turns (120 tasks fit 12 h with margin).

Workflow: `python tools/build_submission.py --tag Sx` (full validation, official compile, reproducible zip,
CPU notebook) → `python kernels/agent_eval/build.py --tag Sx` (GPU dev-panel eval with gold-solvability check) →
`python tools/kaggle_submit.py --tag Sx --hypothesis "..."` (one pending submission, sha-checked, logged in
`runs.csv`). Tests: `pytest tests/test_agent.py`.

## Localization study (paper track) — reproducible pipeline
```
bash scripts/reproduce.sh      # tests -> data -> run -> sensitivity -> audit -> report
```
- `locstudy/` package: `data` (tasks, graphs, content manifest) · `gold` (strict labels from patches) · `signals` (identifier, BM25, embedding, graph, RRF) · `metrics` (Recall@k, MRR, reading-budget, bootstrap CIs, paired bootstrap, exact McNemar, Holm) · `study` (end-to-end + sensitivity) · `audit` (label quality) · `report` (tables, figures, template filling).
- `paper/PAPER.template.md` holds the text; every number is a `{{source:path|fmt}}` slot filled from `results/*.json`, and a missing path fails the build — no hand-typed numbers.
- Every sentence whose truth depends on a direction or significance level carries a `<!-- claim: lhs OP rhs -->` guard next to it; `report.build` raises `ClaimError` if the results contradict the prose.
- `results/summary.json` records data hashes, git commit, library versions and parameters (provenance). Per-task rows stay in `results/private/` (gitignored).
- Parameters fixed in advance in `locstudy.study.Params`; robustness in `results/sensitivity.json`. Post-hoc comparisons are labelled as such in code and paper.
- Model in the loop: `python kernels/build_v2.py` inlines `locstudy` into the Kaggle kernel `kernels/llm-localization` (Gemma 4 31B on 4×L4, offline vLLM); its outputs go to `results/kaggle_v2/` (gitignored) and `python -m locstudy llm` writes `results/llm_summary.json`, `paper/RESULTS_LLM.md`, Figure 4 and section 4.8. Pre-specified tests H1–H3 live in `locstudy.llm_analysis.HYPOTHESES` (committed before the outputs were downloaded); exploratory tests in `EXPLORATORY`.

## Status
- [x] Joined both competitions (rules accepted 2026-10-10)
- [x] Read HARNESS_README (notes above)
- [x] Dev data locally (tasks.jsonl + graphs/ + embeddings/; snapshots only when needed)
- [ ] Local dev loop on the provided sample tasks
- [ ] E0 baseline submission
- [x] Localization study + model-in-the-loop run (114/114 tasks) → paper draft complete (`paper/PAPER.md`)
- [ ] Paper submission by 12 Nov
- [ ] Final selection by 2 Dec
