# Fix asyncpg JSONB Codec Registration Implementation Plan

Source: docs/superpowers/plans/2026-06-25-fix-asyncpg-jsonb-codec.md
Primary-Topic: asyncpg-jsonb-codec
Secondary-Topics: rag-retrieval-pool, document-chunk-metadata

## Key Concepts

- **Root cause**: `asyncpg` does not auto-decode Postgres `jsonb` columns into Python dicts by default — it returns raw JSON strings. `_row_to_chunk_metadata` (in `rag_retrieval.py`) calls `dict()` on that string, which iterates over characters instead of parsing JSON, raising a `ValueError`. The bug lives upstream in pool configuration, not in `_row_to_chunk_metadata` itself (which already handles dicts correctly and needs no change).
- **Fix strategy**: Extract a module-level `_setup_conn` async coroutine that runs once per new connection in the pool (`init=_setup_conn` passed to `asyncpg.create_pool`). It performs two registrations per connection:
  1. `await register_vector(conn)` — from `pgvector.asyncpg`, registers the pgvector type codec (already existing behavior, now moved into `_setup_conn`).
  2. `await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")` — new: registers a JSONB codec so the driver auto-encodes/decodes `jsonb` columns to/from Python dicts transparently.
- **Tech stack involved**: `asyncpg`, `pgvector.asyncpg.register_vector`, Python stdlib `json` (no new dependency; `uv add` not needed — explicitly called out as a global constraint).
- **Target file**: `apps/backend/src/second_brain/nodes/rag_retrieval.py`, specifically the region around lines 21-27 where `_get_rag_pool` previously lived.
- **New function signature**: `_setup_conn(conn: asyncpg.Connection) -> None` — module-level coroutine, used as the `init` callback for `asyncpg.create_pool`.
- **Refactored `_get_rag_pool`**: keeps its global `_rag_pool` singleton pattern guarded by `_rag_pool_lock`; now calls `asyncpg.create_pool(postgres_url, init=_setup_conn)` instead of the old inline setup.
- **Import change**: add `import json` at the top of `rag_retrieval.py`, positioned after `import asyncio` and before `import asyncpg`.
- **TDD workflow mandated**: write two failing tests first (red), confirm failure, implement, confirm pass (green), then run full suite.
  - Test 1 — `test_setup_conn_registers_vector_and_jsonb_codec`: mocks `asyncpg.Connection`, patches `second_brain.nodes.rag_retrieval.register_vector`, asserts `register_vector` awaited once with the mock connection and `conn.set_type_codec` awaited once with `"jsonb"`, `encoder=json.dumps`, `decoder=json.loads`, `schema="pg_catalog"`.
  - Test 2 — `test_get_rag_pool_passes_setup_conn_as_init`: resets module-level `rag_retrieval._rag_pool` to `None`, patches `asyncpg.create_pool`, calls `_get_rag_pool`, asserts `create_pool` awaited once with `init=_setup_conn`, then cleans up by resetting `_rag_pool` to `None` again.
  - Tests inserted into `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py`, positioned after `test_shutdown_rag_pool_closes_and_resets` and before `test_query_pgvector_uses_pool_acquire`.
  - Import alias note: tests use `import json as _json` to avoid shadowing the module's own `json` import.
- **Data flow / symptom**: bug surfaces in production as a `ValueError` crash when reading the `metadata` JSONB column of `document_chunks` during retrieval — i.e. this fix is tied to the `DocumentChunk.chunk_metadata` (SQL column `metadata`) pattern used elsewhere in the codebase.
- **Global constraints for this plan**:
  - All work on branch `fix/resolve-query-issue`, never commit to `main`.
  - `just lint`, `just format`, `just type-check`, `just test-unit` must all pass before declaring done.
  - TDD required — failing test first, confirmed red, then implementation.
  - Conventional Commits enforced by `.hooks/commit-msg`.
  - No new dependencies (`json` is stdlib).
- **Commit message template** (Conventional Commits, `fix(rag-retrieval):` scope) explains the bug and fix rationale in the body: asyncpg doesn't auto-decode JSONB; `_row_to_chunk_metadata` calling `dict()` on a raw string iterates characters and raises `ValueError`; the fix extracts `_setup_conn` to register both `register_vector` and a jsonb codec so every pooled connection auto-decodes JSONB.
- **Task 2 — end-to-end runtime verification** (post-merge, on the running system):
  1. `just up-all` to rebuild/restart backend container; watch `docker logs` for `Application startup complete`.
  2. `curl -s -X POST http://localhost:3001/query -d '{"message": "..."}'` expecting HTTP 200 with body containing `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`, and no `ValueError` in backend logs.
  3. Grep backend logs for `error|exception|traceback` — expect "No errors found" or only unrelated startup noise.
- **Done checklist** ties together: format/lint/type-check/test-unit all green (including the two new tests by name), `POST /query` returns 200 live, and no `ValueError` appears in backend logs after querying.
- **Architectural framing**: this is a pool-initialization concern — codec registration happens per-connection via the `init` hook of `asyncpg.create_pool`, distinct from query-time logic. Related to the project's dual-pool architecture (`asyncpg.Pool` for RAG/memory retrieval vs. `psycopg_pool.AsyncConnectionPool` for LangGraph's checkpointer) documented elsewhere in the codebase — this fix applies only to the `asyncpg` pool used by `rag_retrieval.py` (and shared via `get_pgvector_pool()`), not the psycopg pool.
