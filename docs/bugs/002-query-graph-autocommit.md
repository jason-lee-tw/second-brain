# Bug: POST /query — 500 Internal Server Error on every request

**Date:** 2026-06-24  
**Branch:** fix/resolve-query-issue  
**Severity:** P0 — endpoint completely non-functional

---

## Symptom

`POST /query` returns HTTP 500 on every call.

```
psycopg.errors.ActiveSqlTransaction:
CREATE INDEX CONCURRENTLY cannot run inside a transaction block
```

## Reproduction

```bash
curl -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "session_id": "test"}'
# → 500 Internal Server Error
```

## Stack Trace (abbreviated)

```
File "second_brain/api/routers/query.py", line 28, in _get_graph
    _graph, _pool = await build_query_graph(pg_url)
File "second_brain/graphs/query_graph.py", line 54, in build_query_graph
    await checkpointer.setup()
File "langgraph/checkpoint/postgres/aio.py", line 104, in setup
    await cur.execute(migration)
psycopg.errors.ActiveSqlTransaction:
    CREATE INDEX CONCURRENTLY cannot run inside a transaction block
```

## Five-Why Root Cause

| Why                                                 | Finding                                                                                                                                                                       |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Why does `/query` 500?                              | `checkpointer.setup()` raises `ActiveSqlTransaction` and propagates unhandled                                                                                                 |
| Why does `setup()` raise?                           | LangGraph's migration SQL contains `CREATE INDEX CONCURRENTLY`, which PostgreSQL forbids inside a transaction block                                                           |
| Why is the connection in a transaction?             | `psycopg_pool.AsyncConnectionPool` defaults to `autocommit=False` — every connection wraps statements in an implicit transaction                                              |
| Why was the pool created without `autocommit=True`? | The implementation plan (Task 9) gave reference code without `kwargs={"autocommit": True}`                                                                                    |
| Why did the plan omit it?                           | The author was unaware that `AsyncPostgresSaver.setup()` runs DDL that requires `autocommit=True` — this is a LangGraph-specific requirement not obvious from the API surface |

## Root Cause

`query_graph.py:49` creates `AsyncConnectionPool` without `autocommit=True`:

```python
# BROKEN
pool = AsyncConnectionPool(conninfo=postgres_url, open=False)
```

psycopg3's connection pool defaults `autocommit=False`. LangGraph's `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY` which PostgreSQL requires to run outside any transaction block.

## Fix

```python
# FIXED
pool = AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})
```

See fix plan: `docs/superpowers/plans/2026-06-24-fix-query-graph-autocommit.md`

---

## Follow-up Bug: asyncpg JSONB returned as string

**Date:** 2026-06-25  
**Discovered:** After autocommit fix was applied; `POST /query` still returns 500.

### Symptom

```
ValueError: dictionary update sequence element #0 has length 1; 2 is required
  File "second_brain/nodes/rag_retrieval.py", line 40, in _row_to_chunk_metadata
    d: dict[str, object] = dict(row_meta)
```

### Five-Why Root Cause

| Why | Finding |
| --- | ------- |
| Why does `dict(row_meta)` crash? | `row_meta` is a JSON string; `dict()` on a string iterates characters (length 1 each), not key-value pairs |
| Why is the JSONB column a string? | `asyncpg` does not auto-decode JSONB to Python dicts — it returns raw JSON text by design |
| Why was `dict(row_meta)` written here? | Author assumed asyncpg and psycopg3 behave the same for JSONB; they don't — psycopg3 auto-decodes, asyncpg does not |
| Why was the driver difference not caught? | CLAUDE.md documents the split pools but the JSONB decoding difference between the two drivers wasn't accounted for in `_row_to_chunk_metadata` |
| Why does asyncpg return JSONB as string? | By design: asyncpg defers JSON parsing for performance; auto-decoding requires explicit codec registration via `conn.set_type_codec('jsonb', ...)` |

### Root Cause

`rag_retrieval.py:26` creates `asyncpg.Pool` with only `init=register_vector`. No JSONB codec is registered, so asyncpg returns the `metadata` JSONB column as a raw string. `_row_to_chunk_metadata` then calls `dict(row_meta)` expecting a dict, which fails on a string.

### Fix (chosen: Option B — pool-level codec registration)

Register a JSONB codec in `_get_rag_pool` so all asyncpg queries auto-decode JSONB:

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

See fix plan: `docs/superpowers/plans/2026-06-25-fix-asyncpg-jsonb-codec.md`
