# Fix Plan: AsyncConnectionPool autocommit

Source: docs/superpowers/plans/2026-06-24-fix-query-graph-autocommit.md
Primary-Topic: query-graph-autocommit-fix
Secondary-Topics: langgraph-postgres-checkpointer

## Key Concepts

- Plan fixes a bug where `POST /query` returns HTTP 500 on every request because `AsyncConnectionPool` in `apps/backend/src/second_brain/graphs/query_graph.py` (line 49) is constructed without `autocommit=True`.
- Root cause chain: LangGraph's `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`, which PostgreSQL forbids inside a transaction block; psycopg3's `AsyncConnectionPool` defaults every connection to `autocommit=False`, so every connection implicitly wraps statements in a transaction, causing `psycopg.errors.ActiveSqlTransaction`.
- Related documents: spec at `docs/superpowers/specs/2026-06-24-query-graph-autocommit-fix.md` and bug report at `docs/bugs/002-query-graph-autocommit.md`.
- File map: single-line change to `apps/backend/src/second_brain/graphs/query_graph.py` — add `kwargs={"autocommit": True}` to the `AsyncConnectionPool` constructor call.
- Task 1 follows strict TDD (red → green):
  - Step 1: add a failing async test `test_build_query_graph_pool_uses_autocommit` to `apps/backend/tests/unit/test_graphs/test_query_graph_build.py`. It patches `AsyncConnectionPool` and `AsyncPostgresSaver` in `second_brain.graphs.query_graph`, calls `build_query_graph(...)`, and asserts the pool constructor was called with `conninfo=..., open=False, kwargs={"autocommit": True}`.
  - Step 2: confirm the test fails via `just test-unit` (pool currently constructed without `kwargs`).
  - Step 3: apply the one-line fix — change `pool = AsyncConnectionPool(conninfo=postgres_url, open=False)` to `pool = AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})`.
  - Step 4: run `just format && just lint && just type-check && just test-unit` and confirm all pass, including the new test.
- Task 2 verifies end-to-end on the running system:
  - Step 1: rebuild/restart backend via `just up-all`.
  - Step 2: `curl -X POST http://localhost:3001/query` with a JSON body `{"message": "..."}"` and confirm HTTP 200 with `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext` fields present.
  - Step 3: confirm session continuity (AC-3) — reissue the query with the `sessionId` returned from Step 2 as `session_id`, confirm HTTP 200 and the same `sessionId` is returned.
- Done checklist covers: `just format` passes, `just lint` passes, `just type-check` passes, `just test-unit` passes (including the new autocommit test), `POST /query` returns 200 on the running system, and session continuity is confirmed via a second call reusing `sessionId`.
- Demonstrates the project's two-pool architecture pattern: `psycopg_pool.AsyncConnectionPool` used specifically for LangGraph's `AsyncPostgresSaver` checkpointer in `query_graph.py`, distinct from the `asyncpg.Pool` used elsewhere for pgvector retrieval — each driver has different transaction/autocommit defaults and DDL requirements.
