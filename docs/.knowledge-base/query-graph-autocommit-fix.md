# Query Graph Autocommit Fix

A one-line fix — constructing the query graph's psycopg3 `AsyncConnectionPool` with `autocommit=True` — resolved a P0 bug where `POST /query` returned HTTP 500 on every call because LangGraph's checkpointer setup ran DDL that Postgres forbids inside a transaction.

## Key Concepts

- **Symptom**: every `POST /query` call returned HTTP 500 with `psycopg.errors.ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.
- **Stack trace path**: `second_brain/api/routers/query.py:28 _get_graph` → `second_brain/graphs/query_graph.py:54 build_query_graph` → `await checkpointer.setup()` → `langgraph/checkpoint/postgres/aio.py:104 setup` → raises `ActiveSqlTransaction`.
- **Five-why root cause**:
  1. `/query` 500s because `checkpointer.setup()` raises `ActiveSqlTransaction` unhandled.
  2. LangGraph's migration SQL contains `CREATE INDEX CONCURRENTLY`, which PostgreSQL forbids inside a transaction block.
  3. The connection is in a transaction because psycopg3's `AsyncConnectionPool` defaults to `autocommit=False` — every connection implicitly wraps statements in a transaction.
  4. The pool was created without `autocommit=True` because the implementation plan's reference code for this task was missing `kwargs={"autocommit": True}`.
  5. The plan omitted it because the author didn't know `AsyncPostgresSaver.setup()` runs DDL requiring `autocommit=True` — a LangGraph-specific requirement not obvious from the API surface.
- **Root cause location**: `apps/backend/src/second_brain/graphs/query_graph.py:49` — `AsyncConnectionPool(conninfo=postgres_url, open=False)` constructed without autocommit, used exclusively by LangGraph's `AsyncPostgresSaver` checkpointer for session-state persistence in the query graph.
- **Fix**: `AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})` — a single-line change. No schema changes, no new dependencies, no API contract changes.
- **TDD implementation**: added a failing async test (`test_build_query_graph_pool_uses_autocommit`) that patches `AsyncConnectionPool`/`AsyncPostgresSaver` in `second_brain.graphs.query_graph`, calls `build_query_graph(...)`, and asserts the pool constructor received `kwargs={"autocommit": True}`; confirmed it failed via `just test-unit` before applying the one-line fix, then confirmed `just format && just lint && just type-check && just test-unit` all passed after.
- **Runtime verification (acceptance criteria)**:
  - AC-1: `POST /query {"message": "hello"}` returns HTTP 200 (not 500) against a fresh database.
  - AC-2: response body contains `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`.
  - AC-3: session continuity — reissuing `POST /query` with the previously returned `sessionId` still returns HTTP 200 with the same `sessionId`.
  - AC-4: `just format`, `just lint`, `just type-check`, and `just test-unit` all pass.
- **Scope boundary**: fix applies only to the psycopg3-based `AsyncConnectionPool` in `query_graph.py`; it is unrelated to the separate `asyncpg.Pool` used by RAG/memory retrieval. A distinct follow-up bug (asyncpg not auto-decoding JSONB columns) surfaced only after this fix was applied and is tracked separately.

## Sources

- Bug: POST /query — 500 Internal Server Error on every request — `docs/bugs/002-query-graph-autocommit.md`
- Fix Plan: AsyncConnectionPool autocommit — `docs/superpowers/plans/2026-06-24-fix-query-graph-autocommit.md`
- Spec: Fix AsyncConnectionPool autocommit for LangGraph checkpointer — `docs/superpowers/specs/2026-06-24-query-graph-autocommit-fix.md`

## Related Topics

- [[postgres-connection-pooling]]
- [[query-graph]]
- [[known-issues]]
- [[asyncpg-jsonb-codec]]
- [[database-access-patterns]]
