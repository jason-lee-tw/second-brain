# Spec: Fix `just test-integration` failures (4 independent root causes)

**Date:** 2026-07-03
**Status:** Approved
**Related bug:** `docs/bugs/003-integration-test-failures.md`

---

## Problem

`just test-integration` fails 8/20 tests. Root-caused against the live
Postgres+Ollama stack; see `docs/bugs/003-integration-test-failures.md` for
full five-why analysis of each. Summary:

1. **Conflict-check threshold silently disabled.** `_conflict_check`'s SQL
   does arithmetic on an untyped bind parameter (`1 - $2`), so Postgres
   infers `$2` as `integer` and asyncpg truncates the real threshold (`0.95`)
   to `0`. The check now flags almost any two facts as conflicting.
2. **Async singletons don't survive pytest-asyncio's per-test event loop.**
   `embeddings.py`'s `_client` and `db/pool.py`'s `_pgvector_pool` are
   process-lifetime singletons; pytest-asyncio's default function-scoped
   event loop tears them down mid-suite, causing `RuntimeError: Event loop
is closed` / `asyncpg...InterfaceError`.
3. **Raw-SQL test fixture can't decode the pgvector column.** `db_engine` in
   `test_memory_system.py` has no pgvector codec registered, so embedding
   columns read via `text()` come back as strings, not `list[float]`.
4. **Stale test contradicts an intentional schema decision.** Two tests in
   `test_migration.py` assert an FK that commit `d9bbc69` + migration `002`
   deliberately dropped.

None of these are caused by the Python 3.12→3.13 upgrade — all predate it.

## Change

| #   | File                                                                          | Change                                                                                                                                                                      |
| --- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `apps/backend/src/second_brain/nodes/memory_persistence.py`                   | `_conflict_check`: bind `1 - threshold` directly instead of doing `1 - $2` in SQL                                                                                           |
| 2   | `apps/backend/tests/integration/test_memory_system.py`, `test_query_graph.py` | Add `loop_scope="session"` to the asyncio marker so real embed/pgvector-pool singletons share one event loop for the whole test session                                     |
| 3   | `apps/backend/tests/integration/test_memory_system.py`                        | `db_engine` fixture: register `pgvector.psycopg2.register_vector` via SQLAlchemy's `connect` event                                                                          |
| 4   | `apps/backend/tests/integration/test_migration.py`                            | Flip `test_learned_facts_fk_to_chat_history` / `test_model_corrections_fk_to_chat_history` to assert the FK's _absence_; rename and redocument to reference migration `002` |

## Acceptance Criteria

| #    | Criterion                                                                                                                                                        |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1 | `_conflict_check` with threshold `0.95` does **not** flag "The user is a vegetarian." vs "The user loves hiking." (real cosine similarity 0.60) as a conflict    |
| AC-2 | `_conflict_check` with threshold `0.95` **does** flag "The user lives in Berlin." vs "The user lives in Berlin now." (real cosine similarity 0.97) as a conflict |
| AC-3 | `just test-integration` passes all 20 tests against the live Docker stack, run twice in a row (rules out event-loop flakiness)                                   |
| AC-4 | `just format`, `just lint`, `just type-check`, `just test-unit` all pass with no errors                                                                          |
| AC-5 | `test_learned_facts_fk_to_chat_history` / `test_model_corrections_fk_to_chat_history` (renamed) assert `"chat_history" not in referred`                          |

## Scope

Four targeted changes across 3 files (1 production file, 2 test files). No
schema changes beyond what migration `002` already applied. No new
dependencies — `pgvector.psycopg2` ships with the already-installed
`pgvector` package.

## Out of Scope

- Redesigning `embeddings.py`/`db/pool.py` away from module-level singletons
  (rejected option — production is unaffected since uvicorn keeps one event
  loop alive for the process lifetime; only pytest's per-test loop churn
  triggers this)
- RAGAS evaluation harness
- Any behavior change to the conflict-resolution UX (F1 fix in
  `memory_persistence_node`) — only the threshold comparison itself is fixed
