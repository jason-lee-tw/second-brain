# Database Access Patterns

All database access in the codebase follows exactly two patterns — pgvector cosine-similarity reads via `asyncpg`, and relational writes via SQLModel sync `Session` — never a third.

## Key Concepts

- **Two-Pattern Rule**: all database access follows exactly two patterns; never introduce a third.
- **Pattern 1 — pgvector cosine-similarity reads**: uses the `asyncpg` pool, `async with pool.acquire() as conn`, used by `rag_retrieval` and `memory_retrieval`.
- **Pattern 2 — relational writes (INSERT/UPDATE)**: uses SQLModel sync `Session`, `with Session(engine) as session`, used by `ingestion_agent` and `memory_persistence`.
- **Why two drivers**: `asyncpg` is mandatory for pgvector reads because `pgvector.asyncpg` registers a custom type codec (`register_vector`) on each connection — without it, cosine-similarity queries (`<=>`) fail at the driver level; SQLAlchemy/psycopg cannot substitute here.
- SQLModel sync `Session` is the established write pattern — `db/models.py` defines all five table models (`LearnedFact`, `ModelCorrection`, `DocumentChunk`, etc.), and Alembic uses those same models for migrations, keeping ORM model definitions and runtime writes in sync.
- The shared `asyncpg` pool singleton lives in `second_brain/db/pool.py`, exposing `get_pgvector_pool(postgres_url) -> asyncpg.Pool` and `shutdown_pgvector_pool()`; it is shared across all pgvector-reading nodes (`rag_retrieval`, `memory_retrieval_node` via `get_pgvector_pool()`).
- Nodes import `get_pgvector_pool` directly rather than creating their own pools.
- `shutdown_pgvector_pool` is imported by the app lifespan handler, not by individual nodes; `rag_retrieval.py`'s `shutdown_rag_pool()` is removed once the pool moves to `db/pool.py`.
- Write pattern code example: nodes that write to relational tables import `engine` from `second_brain.db.session` and use `sqlmodel.Session`, e.g. `with Session(engine) as session: session.add(LearnedFact(...)); session.commit()`.
- The sync write call blocks the event loop momentarily — acceptable for write paths (1–3 rows per turn); this pattern must not be used for bulk or high-frequency operations.
- **LangGraph checkpointing** uses a third connection: `psycopg_pool.AsyncConnectionPool` (psycopg3 driver), managed exclusively by LangGraph's `AsyncPostgresSaver` in `graphs/query_graph.py`. This pool is not accessible to application code — it is LangGraph-internal and must not be extended for application queries.

## Connection Pools at Runtime

Three distinct connection pools coexist in the system, each with a different driver and owner:

- `asyncpg.Pool` (asyncpg driver) — owned by `db/pool.py`, shared by read nodes.
- `Engine` (sync, psycopg2/SQLAlchemy) — owned by `db/session.py`, used for writes.
- `AsyncConnectionPool` (psycopg3) — owned by LangGraph's `AsyncPostgresSaver`.

## Open Questions

- **Location of the JSONB-codec init hook**: this page describes the shared asyncpg pool as living in `db/pool.py`, but [[asyncpg-jsonb-codec]] describes the fix (including the `init=_setup_conn` hook) as added directly inside `rag_retrieval.py`'s node-local pool. Unresolved — needs source verification of ordering/location.

## Sources

- Database Access Strategy — `docs/codebase/004-database.md`

## Related Topics

- [[database-schema]]
- [[postgres-connection-pooling]]
- [[pgvector-embeddings]]
- [[asyncpg-jsonb-codec]]
- [[query-graph]]
- [[integration-testing]]
- [[known-issues]]
- [[memory-system]]
- [[query-graph-autocommit-fix]]
