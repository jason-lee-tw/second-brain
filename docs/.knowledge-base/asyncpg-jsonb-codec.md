# asyncpg JSONB Codec

`asyncpg` does not auto-decode Postgres `jsonb` columns, so pooled connections must register a JSONB type codec explicitly alongside the pgvector codec.

## Key Concepts

- **Root cause**: `asyncpg` returns raw JSON strings for `jsonb` columns instead of Python dicts. `_row_to_chunk_metadata` (in `rag_retrieval.py`) called `dict()` on that string, which iterates over characters rather than parsing JSON, raising a `ValueError`. The bug lives upstream in pool configuration, not in `_row_to_chunk_metadata` itself.
- **Fix strategy**: extract a module-level `_setup_conn(conn: asyncpg.Connection) -> None` coroutine passed as `init=_setup_conn` to `asyncpg.create_pool`, so it runs once per new pooled connection. It performs two registrations:
  1. `await register_vector(conn)` — from `pgvector.asyncpg`, registers the pgvector type codec (pre-existing behavior, moved into `_setup_conn`).
  2. `await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")` — new: makes the driver auto-encode/decode `jsonb` columns to/from Python dicts transparently.
- **Target file**: `apps/backend/src/second_brain/nodes/rag_retrieval.py`, around the region where `_get_rag_pool` previously lived (lines 21-27). `_get_rag_pool` keeps its `_rag_pool` singleton pattern guarded by `_rag_pool_lock`, now calling `asyncpg.create_pool(postgres_url, init=_setup_conn)`.
- **Import change**: add `import json` after `import asyncio` and before `import asyncpg`. No new dependency — `json` is stdlib, so `uv add` is not needed.
- **Symptom / data flow**: the bug surfaced in production as a `ValueError` crash when reading the `metadata` JSONB column of `document_chunks` during retrieval, tied to the `DocumentChunk.chunk_metadata` (SQL column `metadata`) pattern.
- **Architectural framing**: codec registration is a pool-initialization concern (the `init` hook of `asyncpg.create_pool`), distinct from query-time logic. This fix applies only to the `asyncpg.Pool` used by `rag_retrieval.py` (shared via `get_pgvector_pool()`), not to the separate `psycopg_pool.AsyncConnectionPool` used by LangGraph's checkpointer — the two pools cannot be shared because they use different drivers.

## TDD Workflow

- Two failing tests were written first (red), confirmed to fail, then the implementation was added (green), followed by the full suite:
  - `test_setup_conn_registers_vector_and_jsonb_codec` — mocks `asyncpg.Connection`, patches `second_brain.nodes.rag_retrieval.register_vector`, asserts `register_vector` awaited once with the mock connection and `conn.set_type_codec` awaited once with `"jsonb"`, `encoder=json.dumps`, `decoder=json.loads`, `schema="pg_catalog"`.
  - `test_get_rag_pool_passes_setup_conn_as_init` — resets module-level `rag_retrieval._rag_pool` to `None`, patches `asyncpg.create_pool`, calls `_get_rag_pool`, asserts `create_pool` awaited once with `init=_setup_conn`, then resets `_rag_pool` to `None` again for cleanup.
  - Both inserted into `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py`, after `test_shutdown_rag_pool_closes_and_resets` and before `test_query_pgvector_uses_pool_acquire`; tests alias `import json as _json` to avoid shadowing the module's own `json` import.

## Verification

- Runtime verification (post-merge, on the running system): `just up-all` to rebuild/restart the backend container, watching `docker logs` for `Application startup complete`; `curl -s -X POST http://localhost:3001/query -d '{"message": "..."}'` expecting HTTP 200 with `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`, and no `ValueError` in backend logs; grepping backend logs for `error|exception|traceback` expecting no unexpected hits.
- Done checklist: format/lint/type-check/test-unit all green (including the two new tests by name), `POST /query` returns 200 live, and no `ValueError` appears in backend logs after querying.

## Open Questions

- **Location of the asyncpg pool singleton**: this page describes the JSONB-codec fix as living in `rag_retrieval.py`'s node-local `_get_rag_pool`/`_rag_pool`, calling `asyncpg.create_pool` directly. [[postgres-connection-pooling]] and [[database-access-patterns]] instead describe the shared pool as already living in `second_brain/db/pool.py` (`get_pgvector_pool()`) with `rag_retrieval.py`'s node-local pooling removed. Unresolved — needs source verification of ordering/location.

## Sources

- [Fix asyncpg JSONB Codec Registration Implementation Plan] — `docs/superpowers/plans/2026-06-25-fix-asyncpg-jsonb-codec.md`

## Related Topics

- [[postgres-connection-pooling]]
- [[pgvector-embeddings]]
- [[database-schema]]
- [[query-graph-autocommit-fix]]
- [[known-issues]]
- [[database-access-patterns]]
- [[document-ingestion-pipeline]]
