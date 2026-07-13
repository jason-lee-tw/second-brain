# Bugs Index

Source: docs/bugs/000-index.md
Primary-Topic: known-issues
Secondary-Topics: database-connection-pooling, integration-testing

## Key Concepts

- This is the index page for `docs/bugs/`, listing documented bugs and their root-cause decisions; each entry links to a dedicated bug doc with a one-sentence summary.
- 001-fix-typecheck-error.md: decisions for fixing 50 basedpyright (static type-checking) errors spread across 12 files.
  - Fix approach: targeted `# type: ignore` comments used sparingly rather than broad suppression.
  - Per-node output `TypedDict`s introduced to give LangGraph node outputs precise, checkable shapes.
  - A shared `get_str_content` utility helper was added, implying repeated content-extraction/type-narrowing logic across nodes that needed a single typed helper.
- 002-query-graph-autocommit.md: P0 (highest severity) production bug.
  - Symptom: `POST /query` endpoint returned HTTP 500.
  - Root cause #1: the psycopg3 connection pool used by the query graph lacked `autocommit=True`, which LangGraph's checkpoint/DDL operations require (LangGraph issues DDL statements that need autocommit semantics, not wrapped in an explicit transaction).
  - This ties to the project's dual-pool architecture: `psycopg_pool.AsyncConnectionPool` is used specifically for LangGraph's `AsyncPostgresSaver`, separate from the `asyncpg.Pool` used for RAG/memory retrieval — the two pools use different drivers and cannot be shared, and the psycopg3 pool needed the autocommit flag set explicitly.
  - Root cause #2 (follow-up bug found while fixing #1): an asyncpg JSONB decoding bug — asyncpg does not decode JSONB columns to Python objects by default, requiring a pool-level codec registration (`set_type_codec` or similar) so JSONB values come back as parsed Python data instead of raw strings.
  - Fix: registered a pool-level codec for JSONB decoding on the asyncpg pool, in addition to setting `autocommit=True` on the psycopg3 pool.
- 003-integration-test-failures.md: P1 severity bug investigation.
  - Symptom: 8 out of 20 `just test-integration` tests were failing.
  - Root-cause analysis traced the 8 failures to 4 independent, unrelated causes (not a single bug):
    1. An untyped SQL parameter silently disabled the memory conflict-check threshold — i.e., a parameter that should have been typed/cast was being passed in a way that made a threshold comparison always false or ineffective, so memory-conflict detection silently did nothing.
    2. Async singletons (module-level or app-level singleton objects) did not survive pytest-asyncio's per-test event loop lifecycle — each test gets a fresh event loop, so objects bound to a previous loop (e.g. connections, locks) became invalid/stale across tests.
    3. A raw-SQL test fixture was missing pgvector decoding — raw SQL queries bypassed the ORM/driver-level vector decoding logic, so pgvector columns weren't converted properly in that fixture's results.
    4. A stale test asserted a foreign-key (FK) constraint that had been deliberately dropped from the schema — the test wasn't updated when the FK was intentionally removed, causing a false failure.
  - This bug doc demonstrates the pattern that a batch of failing tests can stem from multiple independent root causes rather than one shared bug, and includes lessons about event-loop lifecycle in pytest-asyncio and about pgvector decoding needing explicit handling outside the normal ORM path.
- General pattern across this index: bug docs in this project record not just the fix but the root-cause decision/reasoning, intended as durable institutional knowledge (severity labels P0/P1 are used to indicate production impact).
