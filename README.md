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

## Thesis (paper + agent)
**Hybrid graph-retrieval localization**: dense `search_similar_code` → graph expansion via `get_code_neighbors`/`get_code_subgraph` → lexical confirmation (`grep`) → re-rank → patch/test/repair loop. Hypothesis: better file/function localization at fixed budget raises pass rate for a 31B quantized model more than prompt tweaks do.

## Experiments (each measured, nothing reported without a run)
| ID | Variant | Metrics |
|---|---|---|
| E0 | single agent, harness defaults, no retrieval guidance | pass rate, budget used |
| E1 | + dense retrieval skill | + Recall@k / MRR of gold-edited files |
| E2 | + graph expansion | same |
| E3 | + lexical confirmation & re-rank | same |
| E4 | + test-driven repair sub-agent | pass rate, retries, time/issue |
| E5 (optional) | LoRA on tool-use traces | only if E0–E4 plateau and GPU budget allows |

## Status
- [ ] Join competition + accept rules (Emanuele, Kaggle UI)
- [ ] Read `HARNESS_README.md` from the dataset; pin the exact ADK config schema
- [ ] Local dev loop on the provided sample tasks
- [ ] E0 baseline submission
- [ ] Paper draft (from E0–E3 ablation) by 10 Nov, submit by 12 Nov
- [ ] Final selection by 2 Dec
