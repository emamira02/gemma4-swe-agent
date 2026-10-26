# Commit ids before and after the history rewrites of 2026-10-26

The history was rewritten twice on 2026-10-26, before the repository was made public: commit messages (18:20 UTC)
and author/committer email set to the owner's GitHub noreply address (20:20 UTC). File trees, author dates and
commit dates are unchanged (verified commit by commit), so every old id maps to exactly one current commit with the
same tree. The frozen candidate manifests (candidates/*/MANIFEST.json, immutable by design) and earlier notes cite
the old ids; use this table, or find the current commit by tree:

    git log --format="%H %T" | grep <tree id>

| Old id | Current id | Date | Cited in |
|---|---|---|---|
| 136a864 | 6a28d29 | 2026-10-10 | paper 4.9: H1-H3 and the analysis code committed before the model outputs were downloaded |
| 3b64da3 | 17f6c00 | 2026-10-12 | candidates/S1, S2, S3 MANIFEST git_head_at_freeze |
| c91e91f | b03d2dd | 2026-10-13 | candidates/S4 MANIFEST git_head_at_freeze |
| 0404ac0 | 7dea46d | 2026-10-26 | candidates/S5 MANIFEST git_head_at_freeze |
| 4988a94 | d8a7ab6 | 2026-10-26 | candidates/S6 MANIFEST git_head_at_freeze |
| a9f0ee6 | 34ccfde | 2026-10-26 | S6 commit (RESUME.md) |

The candidates' zip sha256 values do not depend on commit ids and still rebuild byte-identically
(tests/test_agent.py::test_frozen_candidates_rebuild_to_their_recorded_sha).
