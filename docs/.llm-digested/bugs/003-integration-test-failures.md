# Bug: `just test-integration` — 8/20 tests failing

Source: docs/bugs/003-integration-test-failures.md
Primary-Topic: integration-testing
Secondary-Topics: database-connection-pooling, pgvector-embeddings

## Key Concepts

- Bug report: `just test-integration` had 8/20 tests failing (P1, integration suite untrustworthy as merge gate), across 4 independent root causes, all predating the Python 3.12→3.13 upgrade (commit `948518b`).
- Failing tests: `test_memory_system.py::test_ac1_fact_written_to_db_with_embedding`, `test_ac2_conflict_detected_not_written`, `test_ac4_correction_written_with_embedding`, `test_full_memory_loop_persist_then_retrieve`; `test_migration.py::test_learned_facts_fk_to_chat_history`, `test_model_corrections_fk_to_chat_history`; `test_query_graph.py::test_ac5_pii_redacted_before_llm_sees_message`, `test_ac6_pii_redacted_in_final_answer`.
- `test_ingestion_graph.py` passed cleanly because it mocks `embed_text` entirely, never exercising the buggy real code paths — a pattern noted as a gap in the other failing suites' coverage.

### Root Cause 1 — conflict-check threshold silently disabled (asyncpg parameter type coercion)

- Location: `apps/backend/src/second_brain/nodes/memory_persistence.py:28-41`, function `_conflict_check`.
- Buggy SQL did arithmetic on an untyped bind parameter inside the query: `WHERE (embedding<=>$1) < (1 - $2)`, with `$2` bound to `settings.memory_conflict_threshold` (0.95).
- Because `$2` only appears inside `1 - $2`, Postgres infers `$2`'s type from the untyped integer literal `1` (i.e. `integer`). asyncpg then encodes the Python float `0.95` into an integer parameter, truncating it to `0`.
- Effect: `(1 - $2)` evaluates to `1`, not `0.05`, so the WHERE clause matches almost everything — the conflict check flagged an unrelated fact ("The user loves hiking.") as conflicting with ("The user is a vegetarian."; real cosine similarity 0.5975, well under the 0.95 threshold).
- Consequence: `_persist_fact` treated the 2nd fact as conflicting with the 1st and skipped the write — `test_ac1` only wrote 1 of 2 facts.
- This bug effectively disabled the conflict check since it was written (commit `a704f72`); never caught before because `test_ac1` was never actually run to green.
- Fix: compute the max-distance cutoff (`max_distance = 1 - threshold`) in Python and bind it directly as `$2`, with SQL changed to `WHERE (embedding<=>$1) < $2` — no arithmetic on the bind parameter inside SQL.
- General lesson: never perform arithmetic on an untyped bind parameter inside raw SQL; Postgres/asyncpg can silently coerce/truncate the type.

### Root Cause 2 — async singletons don't survive pytest-asyncio's per-test event loop

- Symptoms: `RuntimeError: Event loop is closed` during task `memory_retrieval_node`; `asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress` in `asyncpg/pool.py` release.
- Affected singletons: `embeddings.py:5` (`_client = httpx.AsyncClient(...)`) and `db/pool.py:14-15` (`_pgvector_pool`, `_pgvector_pool_lock`) — both module-level, created once and cached for the whole process.
- Root cause: pytest-asyncio's default is a new event loop per test function; once that loop closes, any connection/lock bound to it becomes unusable, so the 2nd/4th async DB test in a module (that reuses the real singleton) crashes.
- Why `test_ingestion_graph.py` doesn't see this: it patches `embed_text` with an `AsyncMock` in every test, never touching the real singleton.
- Why this doesn't happen in production: uvicorn keeps exactly one event loop alive for the entire process lifetime, so singletons never outlive their loop there — this is a test-only issue, not a production bug.
- Fix: give `test_memory_system.py` and `test_query_graph.py` a session-scoped event loop via pytest-asyncio's `loop_scope="session"` marker, so singletons are created once and never observe a closed loop — mirroring the single-event-loop-per-process lifetime already true in production.

### Root Cause 3 — raw-SQL test fixture can't decode the pgvector column

- Symptom: `AssertionError: assert 12764 == 1024`, where `12764 = len('[-0.00730595,-0.015381461,...]')` — i.e. the embedding came back as the pgvector text literal (a string of length 12764 characters) instead of a parsed `list[float]` of dimensionality 1024.
- Cause: `test_memory_system.py`'s `db_engine` fixture is a plain `create_engine(sync_url)` using psycopg2 with no pgvector registration; psycopg2 has no adapter registered for Postgres's custom `vector` type on this engine, so raw `text()` SQL queries fall back to the raw text representation.
- Contrast: the ORM path (`SQLModel` + `pgvector.sqlalchemy.Vector` column type in `db/models.py`) decodes vectors automatically — but this fixture bypasses the ORM to read back rows across the SQLModel session boundary, opening its own connection instead.
- Fix: register the `pgvector.psycopg2.register_vector` codec on every connection from that engine via SQLAlchemy's `connect` event hook.

### Root Cause 4 — stale test contradicts an intentional later schema decision

- Symptom: `test_learned_facts_fk_to_chat_history` fails with `AssertionError: assert 'chat_history' in set()`.
- Cause: `learned_facts.source_session` has no foreign key to `chat_history`. Migration `002_drop_source_session_fk.py` explicitly drops it.
- Why it was dropped: commit `d9bbc69` ("fix(db): drop source_session FK — chat_history not written by app") — `chat_history` is never written by the application; LangGraph uses its own checkpoint tables, so the FK could never be satisfied.
- Why the test still expected the FK: `test_migration.py` hadn't been touched since the very first commit (`af430a2`), predating `d9bbc69` — no integration test run had closed the loop between the schema fix and the test suite until now.
- Affects both `test_learned_facts_fk_to_chat_history` and `test_model_corrections_fk_to_chat_history`.
- Fix: flip both assertions to confirm the FK's absence (as a regression guard against accidental reintroduction), and rename/redocument the tests to reference migration 002.

### Cross-cutting notes

- All four root causes predate the Python 3.12→3.13 upgrade in commit `948518b` — the upgrade did not cause them, it just surfaced them via a fresh integration test run.
- Bug doc references a fix plan at `docs/superpowers/plans/2026-07-03-integration-test-fixes.md` for all four root causes.
- Bug filed on branch `fix/000-integration-test`, dated 2026-07-03, severity P1 because the integration suite could not be trusted as a merge gate.
- Related architectural facts surfaced by this bug: two separate async DB access layers exist — `asyncpg.Pool` (`db/pool.py`, used by `rag_retrieval` and `memory_retrieval_node` via `get_pgvector_pool()`) and SQLModel/psycopg2 for schema/ORM access — and `DocumentChunk`/`LearnedFacts`/`ModelCorrections` tables use pgvector `embedding` columns requiring correct type handling on both the write path (asyncpg bind parameters) and read path (psycopg2 vector codec registration).
