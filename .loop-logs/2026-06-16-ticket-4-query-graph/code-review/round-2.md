# Code Review — Round 2

**Timestamp:** 2026-07-20T06:45:00Z
**Loop iteration:** 2 of ≤5
**Model tier:** Sonnet (diff: 2041 lines / 30 files changed — over the 20-file threshold, session model already runs 1M-context Sonnet 5)

## Findings

| ID  | Severity | Summary | Evidence (file:line) |
| --- | -------- | ------- | --------------------- |
| N1  | minor    | F4's fix introduced a second unlocked lazy-singleton (`_pool` in `rag_retrieval.py`), duplicating the exact race shape of the already-deferred `_get_graph()` singleton in `query.py` (F7). Two concurrent cold-start requests can each create a pool; the loser's pool leaks (never closed by `shutdown()`). | `apps/backend/src/second_brain/nodes/rag_retrieval.py:10,18-21` (cf. `apps/backend/src/second_brain/api/routers/query.py:16,19-26`) |
| N2  | none (verification note) | F1/F2/F4 verified to interact correctly end-to-end — `redact_outbound`'s new `AIMessage` is checkpointed via the autocommit-fixed pool and correctly re-surfaces in `synthesis.py`'s history window on the next turn. Confirmed by code trace + live integration test run. | `apps/backend/src/second_brain/nodes/synthesis.py:68`; `apps/backend/tests/integration/test_query_graph.py:157-214` |
| N3  | none (verification note) | The manually-resolved `test_query_graph.py` merge conflict (F1 vs F2, both touching the same integration test file) is clean — no dropped assertions, no duplicated tests, no leftover markers. | `apps/backend/tests/integration/test_query_graph.py:223-253` |

No blocking or important issues. All 4 round-1 fixes hold up individually and in combination — `just lint` clean, 147 unit tests pass, 4/4 query-graph integration tests pass live against Postgres.

## Disposition

- Actionable (blocking + important) — to fix this iteration: none
- Deferred (minor — NOT handled yet): N1 (new `rag_retrieval._pool` race, same class as F7 — worth fixing together later), F5 (DSN-stripping duplication, unchanged), F6 (local rate limiter, unchanged), F7 (`_get_graph()` race, unchanged), F8 (dual query-module import in `main.py`, unchanged)
