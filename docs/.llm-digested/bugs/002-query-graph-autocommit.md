# Bug: POST /query — 500 Internal Server Error on every request

Source: docs/bugs/002-query-graph-autocommit.md
Primary-Topic: postgres-connection-pools
Secondary-Topics: langgraph-checkpointer, asyncpg-jsonb-decoding

## Key Concepts

- **Symptom**: `POST /query` returns HTTP 500 on every call, with `psycopg.errors.ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.
- **Reproduction**: `curl -X POST http://localhost:3001/query -H "Content-Type: application/json" -d '{"message": "hello", "session_id": "test"}'` → 500.
- **Stack trace path**: `second_brain/api/routers/query.py:28 _get_graph` → `second_brain/graphs/query_graph.py:54 build_query_graph` → `await checkpointer.setup()` → `langgraph/checkpoint/postgres/aio.py:104 setup` → raises `ActiveSqlTransaction`.
- **Five-Why chain (autocommit bug)**:
  1. `/query` 500s because `checkpointer.setup()` raises `ActiveSqlTransaction` unhandled.
  2. LangGraph's migration SQL contains `CREATE INDEX CONCURRENTLY`, which PostgreSQL forbids inside a transaction block.
  3. The connection is in a transaction because `psycopg_pool.AsyncConnectionPool` defaults to `autocommit=False` — every connection implicitly wraps statements in a transaction.
  4. The pool was created without `autocommit=True` because the implementation plan (Task 9) gave reference code missing `kwargs={"autocommit": True}`.
  5. The plan omitted it because the author didn't know `AsyncPostgresSaver.setup()` runs DDL requiring `autocommit=True` — a LangGraph-specific requirement not obvious from the API surface.
- **Root cause location**: `query_graph.py:49` — `AsyncConnectionPool(conninfo=postgres_url, open=False)` created without autocommit.
- **Why it matters**: psycopg3's `AsyncConnectionPool` defaults `autocommit=False`; LangGraph's `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`, which Postgres requires to run outside any transaction block. Any LangGraph checkpointer setup against psycopg3 needs autocommit enabled or setup will always fail.
- **Fix**: `AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})`.
- **Fix plan reference**: `docs/superpowers/plans/2026-06-24-fix-query-graph-autocommit.md`.
- **Branch**: `fix/resolve-query-issue`. **Severity**: P0 — endpoint completely non-functional. **Date**: 2026-06-24.

## Follow-up Bug: asyncpg JSONB returned as string

- **Discovered**: 2026-06-25, after the autocommit fix was applied; `POST /query` still returned 500 (different error).
- **Symptom**: `ValueError: dictionary update sequence element #0 has length 1; 2 is required` at `second_brain/nodes/rag_retrieval.py:40 _row_to_chunk_metadata`, from `dict(row_meta)`.
- **Five-Why chain (JSONB bug)**:
  1. `dict(row_meta)` crashes because `row_meta` is a JSON string, and `dict()` on a string iterates characters (length 1 each), not key-value pairs.
  2. The JSONB column is a string because `asyncpg` does not auto-decode JSONB to Python dicts — it returns raw JSON text by design.
  3. `dict(row_meta)` was written assuming asyncpg and psycopg3 behave the same for JSONB; they don't — psycopg3 auto-decodes JSONB, asyncpg does not.
  4. This driver difference wasn't caught because CLAUDE.md documents the two separate Postgres pools but didn't call out the JSONB decoding difference between the drivers in `_row_to_chunk_metadata`.
  5. asyncpg returns JSONB as string by design: it defers JSON parsing for performance; auto-decoding requires explicit codec registration via `conn.set_type_codec('jsonb', ...)`.
- **Root cause location**: `rag_retrieval.py:26` — the `asyncpg.Pool` is created with only `init=register_vector`, no JSONB codec registered.
- **Chosen fix (Option B — pool-level codec registration)**: register a JSONB codec in `_get_rag_pool` so all asyncpg queries auto-decode JSONB:
  ```python
  import json

  async def _setup_conn(conn: asyncpg.Connection) -> None:
      await register_vector(conn)
      await conn.set_type_codec(
          "jsonb",
          encoder=json.dumps,
          decoder=json.loads,
          schema="pg_catalog",
      )

  _rag_pool = await asyncpg.create_pool(postgres_url, init=_setup_conn)
  ```
- **Fix plan reference**: `docs/superpowers/plans/2026-06-25-fix-asyncpg-jsonb-codec.md`.
- **Broader architectural note**: This project intentionally runs two separate Postgres connection pools — `asyncpg.Pool` (used by `rag_retrieval` / `memory_retrieval_node`) and `psycopg_pool.AsyncConnectionPool` (used by LangGraph's `AsyncPostgresSaver` in `query_graph.py`) — because they are different drivers that cannot share a pool. Each driver has its own default behaviors around transactions (psycopg3 autocommit default) and type decoding (asyncpg JSONB decoding) that must be configured explicitly per-driver rather than assumed to match.
