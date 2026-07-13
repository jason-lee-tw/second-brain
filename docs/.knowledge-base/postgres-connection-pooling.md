# Postgres Connection Pooling

Two Postgres connection pools coexist in the backend — an `asyncpg.Pool` for pgvector reads and a `psycopg_pool.AsyncConnectionPool` for LangGraph checkpointing — and each driver's defaults (transaction mode, JSONB decoding) must be configured explicitly because the pools cannot be shared or assumed to behave alike.

## Key Concepts

- **Two pools, two drivers, cannot share**: `asyncpg.Pool` (asyncpg driver) handles pgvector cosine-similarity reads; `psycopg_pool.AsyncConnectionPool` (psycopg3 driver) is used exclusively by LangGraph's `AsyncPostgresSaver` for checkpointing in `query_graph.py`. They cannot share a connection pool because they are different drivers with different type-decoding and transaction semantics.
- **Shared asyncpg singleton**: the asyncpg pool lives in `second_brain/db/pool.py` as a single singleton exposing `get_pgvector_pool()` and `shutdown_pgvector_pool()`, guarded by an `asyncio.Lock` so it is created once. Both `rag_retrieval.py` and `memory_retrieval_node` read pgvector through this one shared pool rather than each owning an independent pool — a memory node depending on the RAG node's own pool would have been the wrong direction of coupling, so the pool was promoted out of `rag_retrieval.py` into its own module. `rag_retrieval.py`'s previous node-local `_get_rag_pool`/`shutdown_rag_pool` were removed once the shared pool existed; the app lifespan handler now imports `shutdown_pgvector_pool` from `db/pool.py` instead.
- **psycopg3 pool is LangGraph-only**: the `AsyncConnectionPool` in `query_graph.py` is created and managed for `AsyncPostgresSaver` checkpointing specifically — it is not a general-purpose pool for application queries.
- **Per-connection setup via pool `init=` hook**: the asyncpg pool's `init` callback (`_setup_conn`) runs once per new pooled connection and performs two registrations: `await register_vector(conn)` (pgvector type codec, from `pgvector.asyncpg`) and `await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")` (JSONB codec). Codec registration is a pool-initialization concern, distinct from query-time logic — every connection the pool ever creates goes through the same `init` coroutine.
- **Driver defaults are not interchangeable and must be set explicitly**:
  - psycopg3's `AsyncConnectionPool` defaults to `autocommit=False`, wrapping every connection in an implicit transaction. LangGraph's `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`, which PostgreSQL forbids inside a transaction block — so the pool must be constructed with `AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})`. This was a P0 production bug (`POST /query` 500ing on every call); the full five-why root-cause narrative and fix are documented on [[query-graph-autocommit-fix]] rather than repeated here.
  - `asyncpg` does not auto-decode Postgres `jsonb` columns to Python dicts by default — it returns raw JSON strings, unlike psycopg3 which auto-decodes JSONB. Code that assumes both drivers behave the same for JSONB (e.g. calling `dict()` directly on a fetched value) will fail once run against the asyncpg pool. Fixed by registering the JSONB codec above. Full fix narrative and TDD plan on [[asyncpg-jsonb-codec]].
  - These two driver-default gaps were not caught earlier because the project's dual-pool architecture was documented (which pool is used where) without also documenting each driver's default transaction/decoding behavior — the lesson is that pool configuration notes need to cover driver defaults, not just which pool a node uses.
- **Relational writes use a third, separate access path**: `memory_persistence_node` and `ingestion_agent` write via a SQLModel sync `Session(engine)` (psycopg2), not through either pooled async driver. This write path is a distinct database-access pattern, not a third connection pool for reads — see [[database-access-patterns]] for the full read/write pattern split.
- **Pool-bound async singletons don't survive pytest-asyncio's per-test event loop**: module-level singletons that hold onto a connection/lock created against one event loop (e.g. `db/pool.py`'s `_pgvector_pool`/`_pgvector_pool_lock`) break once that event loop closes, because pytest-asyncio's default gives each test function a fresh event loop. Symptoms: `RuntimeError: Event loop is closed`, and `asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress` from `asyncpg/pool.py` on release. This does not happen in production because uvicorn keeps exactly one event loop alive for the whole process lifetime, so the singleton never outlives its loop there — it is a test-only issue. Fix: give tests that touch the real singleton pool a session-scoped event loop (pytest-asyncio's `loop_scope="session"` marker), so the pool is created once per test session and mirrors the single-event-loop-per-process lifetime that already holds in production.

## Open Questions

- **Location of the JSONB-codec init hook**: this page describes the shared asyncpg pool as living in `db/pool.py`, but [[asyncpg-jsonb-codec]] describes the fix (including the `init=_setup_conn` hook) as added directly inside `rag_retrieval.py`'s node-local pool. Unresolved — needs source verification of ordering/location.

## Sources

- Bugs Index — `docs/bugs/000-index.md`
- Bug: POST /query — 500 Internal Server Error on every request — `docs/bugs/002-query-graph-autocommit.md`
- Bug: `just test-integration` — 8/20 tests failing — `docs/bugs/003-integration-test-failures.md`
- System Architecture — `docs/codebase/003-system-architecture.md`
- Ticket 5 Memory System — Grilling Session Decisions — `docs/grilling-sessions/2026-06-26-ticket-5-grilling-decisions.md`
- Memory System Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-5-memory.md`
- Fix asyncpg JSONB Codec Registration Implementation Plan — `docs/superpowers/plans/2026-06-25-fix-asyncpg-jsonb-codec.md`

## Related Topics

- [[query-graph-autocommit-fix]]
- [[asyncpg-jsonb-codec]]
- [[database-access-patterns]]
- [[memory-system]]
- [[known-issues]]
- [[integration-testing]]
- [[query-graph]]
- [[pgvector-embeddings]]
- [[system-architecture]]
- [[database-schema]]
- [[second-brain-architecture]]
