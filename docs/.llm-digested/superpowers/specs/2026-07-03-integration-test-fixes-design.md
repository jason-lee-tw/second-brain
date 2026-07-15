# Spec: Fix `just test-integration` failures (4 independent root causes)

Source: docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md
Primary-Topic: integration-testing
Secondary-Topics: memory-persistence, database-schema

## Key Concepts

- Spec dated 2026-07-03, status Approved, related to bug doc `docs/bugs/003-integration-test-failures.md`.
- `just test-integration` fails 8/20 tests before this fix; all 4 root causes were diagnosed against the live Postgres+Ollama stack via five-why analysis.
- None of the 4 root causes are caused by the Python 3.12→3.13 upgrade — all predate it.
- **Root cause 1 — conflict-check threshold silently disabled.** `_conflict_check`'s SQL does arithmetic on an untyped bind parameter (`1 - $2`), so Postgres infers `$2` as `integer` and asyncpg truncates the real threshold value (`0.95`) down to `0`. Effect: the check flags almost any two facts as conflicting because the effective threshold is 0.
- **Root cause 2 — async singletons don't survive pytest-asyncio's per-test event loop.** `embeddings.py`'s `_client` and `db/pool.py`'s `_pgvector_pool` are process-lifetime singletons. pytest-asyncio's default function-scoped event loop tears them down mid-suite, causing `RuntimeError: Event loop is closed` and `asyncpg...InterfaceError`.
- **Root cause 3 — raw-SQL test fixture can't decode the pgvector column.** The `db_engine` fixture in `test_memory_system.py` has no pgvector codec registered, so embedding columns read via SQLAlchemy `text()` come back as raw strings instead of `list[float]`.
- **Root cause 4 — stale test contradicts an intentional schema decision.** Two tests in `test_migration.py` assert the existence of a foreign key that commit `d9bbc69` plus migration `002` deliberately dropped.
- Change 1: in `apps/backend/src/second_brain/nodes/memory_persistence.py`, `_conflict_check` should bind `1 - threshold` directly in Python rather than computing `1 - $2` inside the SQL, avoiding Postgres's incorrect type inference on the bind parameter.
- Change 2: in `apps/backend/tests/integration/test_memory_system.py` and `test_query_graph.py`, add `loop_scope="session"` to the asyncio marker so the real embed client and pgvector-pool singletons share one event loop for the whole test session instead of being torn down per test.
- Change 3: in `apps/backend/tests/integration/test_memory_system.py`, the `db_engine` fixture should register `pgvector.psycopg2.register_vector` via SQLAlchemy's `connect` event so raw-SQL reads of vector columns decode correctly.
- Change 4: in `apps/backend/tests/integration/test_migration.py`, flip `test_learned_facts_fk_to_chat_history` and `test_model_corrections_fk_to_chat_history` to assert the FK's absence instead of presence; rename and redocument them to reference migration `002` as the source of truth.
- Acceptance criteria:
  - AC-1: `_conflict_check` with threshold `0.95` must NOT flag "The user is a vegetarian." vs "The user loves hiking." (real cosine similarity 0.60) as a conflict.
  - AC-2: `_conflict_check` with threshold `0.95` MUST flag "The user lives in Berlin." vs "The user lives in Berlin now." (real cosine similarity 0.97) as a conflict.
  - AC-3: `just test-integration` passes all 20 tests against the live Docker stack, run twice in a row (rules out event-loop flakiness).
  - AC-4: `just format`, `just lint`, `just type-check`, `just test-unit` all pass with no errors.
  - AC-5: the renamed FK tests (`test_learned_facts_fk_to_chat_history` / `test_model_corrections_fk_to_chat_history`) assert `"chat_history" not in referred`.
- Scope: four targeted changes across 3 files (1 production file: `memory_persistence.py`; 2 test files: `test_memory_system.py`/`test_query_graph.py` and `test_migration.py`). No schema changes beyond what migration `002` already applied. No new dependencies — `pgvector.psycopg2` ships with the already-installed `pgvector` package.
- Out of scope: redesigning `embeddings.py`/`db/pool.py` away from module-level singletons was considered and rejected — production is unaffected because uvicorn keeps one event loop alive for the process lifetime; only pytest's per-test event-loop churn triggers the issue. Also out of scope: the RAGAS evaluation harness, and any behavior change to the conflict-resolution UX (the F1 fix in `memory_persistence_node`) beyond fixing the threshold comparison itself.
