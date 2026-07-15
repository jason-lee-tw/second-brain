# Database Access Strategy

Source: docs/codebase/004-database.md
Primary-Topic: database-access-patterns
Secondary-Topics: database-schema

## Key Concepts

- Two-Pattern Rule: all database access in the codebase follows exactly two patterns — never introduce a third.
- Pattern 1 — pgvector cosine-similarity reads: uses `asyncpg` pool, `async with pool.acquire() as conn`, used by `rag_retrieval` and `memory_retrieval`.
- Pattern 2 — relational writes (INSERT/UPDATE): uses SQLModel sync `Session`, `with Session(engine) as session`, used by `ingestion_agent` and `memory_persistence`.
- Why two drivers: `asyncpg` is mandatory for pgvector reads because `pgvector.asyncpg` registers a custom type codec (`register_vector`) on each connection — without it, cosine-similarity queries (`<=>`) fail at the driver level; SQLAlchemy/psycopg cannot substitute here.
- SQLModel sync `Session` is the established write pattern — `db/models.py` defines all five table models (`LearnedFact`, `ModelCorrection`, `DocumentChunk`, etc.), and Alembic uses those same models for migrations, keeping ORM model definitions and runtime writes in sync.
- Shared asyncpg pool singleton lives in `second_brain/db/pool.py`, exposing `get_pgvector_pool(postgres_url) -> asyncpg.Pool` and `shutdown_pgvector_pool()`; it is shared across all pgvector-reading nodes (`rag_retrieval`, `memory_retrieval_node` via `get_pgvector_pool()`).
- Nodes import `get_pgvector_pool` directly rather than creating their own pools.
- `shutdown_pgvector_pool` is imported by the app lifespan handler, not by individual nodes; `rag_retrieval.py`'s `shutdown_rag_pool()` is removed once the pool moves to `db/pool.py`.
- Write pattern code example: nodes that write to relational tables import `engine` from `second_brain.db.session` and use `sqlmodel.Session`, e.g. `with Session(engine) as session: session.add(LearnedFact(...)); session.commit()`.
- The sync write call blocks the event loop momentarily — acceptable for write paths (1–3 rows per turn); this pattern must not be used for bulk or high-frequency operations.
- LangGraph Checkpointing uses a third connection: `psycopg_pool.AsyncConnectionPool` (psycopg3 driver), managed exclusively by LangGraph's `AsyncPostgresSaver` in `graphs/query_graph.py`. This pool is not accessible to application code — it is LangGraph-internal and must not be extended for application queries.
- Connection count at runtime table: `asyncpg.Pool` (asyncpg driver) owned by `db/pool.py`, shared by nodes; `Engine` (sync, psycopg2/SQLAlchemy) owned by `db/session.py` for writes; `AsyncConnectionPool` (psycopg3) owned by LangGraph `AsyncPostgresSaver`. Three distinct connection pools coexist in the system, each with a different driver and owner.
- Database schema (ER diagram) defines five tables:
  - `chat_history`: `session_id` UUID7 PK, `thread_data` JSONB, `created_at`/`updated_at` TIMESTAMP.
  - `ingested_documents`: `id` UUID PK, `filename` TEXT, `source_url` TEXT, `content_hash` TEXT, `status` TEXT, `ingested_at` TIMESTAMP.
  - `document_chunks`: `id` UUID PK, `doc_id` UUID FK, `content` TEXT, `embedding` VECTOR, `chunk_index` INT, `metadata` JSONB, `created_at` TIMESTAMP.
  - `learned_facts`: `id` UUID PK, `fact` TEXT, `embedding` VECTOR, `source_session` UUID7 FK, `confidence` FLOAT, `created_at`/`updated_at` TIMESTAMP.
  - `model_corrections`: `id` UUID PK, `original_answer` TEXT, `correction` TEXT, `root_cause` TEXT, `embedding` VECTOR, `source_session` UUID7 FK, `created_at` TIMESTAMP.
- Relationships: `ingested_documents ||--o{ document_chunks` ("has"); `chat_history ||--o{ learned_facts` ("source_session"); `chat_history ||--o{ model_corrections` ("source_session").
- Embedding field semantics: `document_chunks.embedding` encodes chunk text + contextual header, used for pgvector cosine similarity RAG retrieval; `learned_facts.embedding` encodes the `fact` field for cosine-similarity memory retrieval per query; `model_corrections.embedding` encodes the `correction` field, NOT `original_answer`, so similarity search surfaces the correct answer rather than the mistake.
- Python ORM note: `DocumentChunk` uses the Python attribute `chunk_metadata` mapped to the SQL column `metadata` to avoid a SQLAlchemy name conflict — use `.chunk_metadata` in Python code, but `metadata` in raw SQL.
