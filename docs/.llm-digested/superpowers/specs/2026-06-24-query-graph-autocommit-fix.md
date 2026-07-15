# Fix AsyncConnectionPool autocommit for LangGraph checkpointer

Source: docs/superpowers/specs/2026-06-24-query-graph-autocommit-fix.md
Primary-Topic: postgres-connection-pool
Secondary-Topics: langgraph-checkpointer, query-graph

## Key Concepts

- Spec dated 2026-06-24, status Approved, related bug documented at `docs/bugs/002-query-graph-autocommit.md`.
- Problem: `POST /query` returns HTTP 500 on every call because `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY` inside a psycopg3 implicit transaction block. `CREATE INDEX CONCURRENTLY` cannot execute inside a transaction block in Postgres, so it fails.
- `AsyncPostgresSaver` is LangGraph's checkpointer implementation backed by Postgres, used for persisting graph state/session continuity in the query graph.
- Root cause: the `AsyncConnectionPool` used in `apps/backend/src/second_brain/graphs/query_graph.py` is created without `autocommit=True`, so psycopg3 wraps each pooled connection's statements in an implicit transaction, which is incompatible with `CREATE INDEX CONCURRENTLY` used by the checkpointer's schema migration/setup step.
- Fix: construct the `AsyncConnectionPool` in `query_graph.py` with `autocommit=True` so LangGraph's checkpoint schema migrations run outside any transaction block.
- Scope is deliberately minimal: a one-line change in `apps/backend/src/second_brain/graphs/query_graph.py`. No schema changes, no new dependencies, no API contract changes.
- Acceptance criteria:
  - AC-1: `POST /query {"message": "hello"}` returns HTTP 200 (not 500) against a fresh database.
  - AC-2: `POST /query` response body contains `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`.
  - AC-3: Calling `POST /query` a second time with the previously returned `sessionId` returns HTTP 200 (verifies session continuity still works after the fix).
  - AC-4: `just format`, `just lint`, `just type-check`, and `just test-unit` all pass with no errors.
- Out of scope for this spec: memory agent, conflict detection, fact persistence work (tracked as a separate ticket, "Ticket 5"), RAGAS evaluation, and updating the implementation plan document (tracked as a separate chore).
- Architectural context (from project conventions): the codebase has two separate Postgres connection pools that cannot be shared because they use different drivers — an `asyncpg.Pool` in `db/pool.py` (used by `rag_retrieval` and `memory_retrieval_node` via `get_pgvector_pool()`), and a `psycopg_pool.AsyncConnectionPool` in `graphs/query_graph.py` specifically required by LangGraph's `AsyncPostgresSaver`. This spec's fix applies only to the second (psycopg3-based) pool.
