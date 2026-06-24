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
