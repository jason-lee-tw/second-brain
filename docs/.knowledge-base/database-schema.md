# Database Schema

The Second Brain's `app_postgres` database has five SQLModel-defined, Alembic-migrated tables — three plain relational tables and two pgvector-backed embedding tables — that store ingested documents, chat/session state, and long-term memory.

## Key Concepts

- Five tables, all defined in `db/models.py` as SQLModel `table=True` classes and created via Alembic migrations (schema is managed exclusively through Alembic, never by hand):
  - `chat_history` — LangGraph session/checkpoint state: `session_id` (UUID7 string, PK, also the LangGraph `thread_id`), `thread_data` (JSONB, default `{}`), `created_at`/`updated_at` (TIMESTAMP).
  - `ingested_documents` — ingestion dedup record: `id` (UUID PK), `filename` (TEXT), `source_url` (TEXT, nullable — null for local files), `content_hash` (TEXT, MD5 of raw file content, used to skip re-ingestion), `status` (TEXT: `'processed'|'failed'`), `ingested_at` (TIMESTAMP).
  - `document_chunks` — RAG document store: `id` (UUID PK), `doc_id` (UUID, FK → `ingested_documents.id`), `content` (TEXT, chunk text with an LLM-generated contextual header prepended), `embedding` (`VECTOR(1024)`, nullable), `chunk_index` (INT), `metadata` (JSONB, nullable — holds source/heading_path/content_type/char_count), `created_at` (TIMESTAMP).
  - `learned_facts` — long-term memory: `id` (UUID PK), `fact` (TEXT, PII-scrubbed), `embedding` (`VECTOR(1024)`), `source_session` (UUID7, originally FK → `chat_history.session_id`), `confidence` (FLOAT), `created_at`/`updated_at` (TIMESTAMP).
  - `model_corrections` — long-term memory: `id` (UUID PK), `original_answer` (TEXT), `correction` (TEXT), `root_cause` (TEXT), `embedding` (`VECTOR(1024)`), `source_session` (UUID7, originally FK → `chat_history.session_id`), `created_at` (TIMESTAMP).
- Python/SQL naming divergence: `DocumentChunk`'s Python attribute is `chunk_metadata`, mapped via `sa_column=Column("metadata", JSONB, ...)` to the SQL column `metadata` — done to avoid shadowing SQLModel/SQLAlchemy's class-level `metadata` attribute inherited from the declarative base. Rule: use `.chunk_metadata` in Python code, `metadata` in raw SQL/migrations/inspection. Documented as the single deliberate divergence from spec field names.
- Embedding field semantics (all embedding columns use `pgvector.sqlalchemy.Vector(1024)`, dimension 1024 chosen to match the `qwen3-embedding:0.6b` Ollama model): `document_chunks.embedding` encodes chunk text plus its contextual header (for RAG retrieval); `learned_facts.embedding` encodes the `fact` field (for memory retrieval); `model_corrections.embedding` encodes the `correction` field — deliberately **not** `original_answer` — so cosine-similarity retrieval surfaces the correct answer rather than the original mistake.
- Original relationships (as first migrated in `001_initial_schema.py`): `ingested_documents ||--o{ document_chunks` ("has"); `chat_history ||--o{ learned_facts` ("source_session"); `chat_history ||--o{ model_corrections` ("source_session").
- Schema evolution — migration `002_drop_source_session_fk.py` (shipped in commit `d9bbc69`) deliberately dropped the foreign key from `learned_facts.source_session` and `model_corrections.source_session` to `chat_history.session_id`, because `chat_history` is never written by the application. `source_session` remains a UUID7 column on both tables but is no longer FK-constrained. Two integration tests in `test_migration.py` were originally left asserting the FK still existed and had to be flipped (renamed to `test_learned_facts_no_fk_to_chat_history` / `test_model_corrections_no_fk_to_chat_history`, asserting `"chat_history" not in referred`) to match this shipped, intentional change.
- pgvector setup: the `pgvector/pgvector:pg16` Docker image ships the pgvector shared library pre-installed, but the extension still must be enabled per-database — the first migration runs `CREATE EXTENSION IF NOT EXISTS vector` before creating any table with a `VECTOR` column. `downgrade()` drops tables in reverse dependency order then runs `DROP EXTENSION IF EXISTS vector`.
- `alembic check` is used as a drift check — it must report "No new upgrade operations detected," confirming the SQLModel models and the applied migrations stay in sync.
- Access pattern implication of this schema: `asyncpg` (with `pgvector.asyncpg`'s `register_vector` codec) is required for any pgvector cosine-similarity read (`<=>` operator) against `document_chunks`, `learned_facts`, or `model_corrections`; SQLModel's sync `Session` is used for the relational INSERT/UPDATE writes to all five tables. Raw-SQL test fixtures that bypass the ORM (e.g. in `test_memory_system.py`) must separately register the `pgvector.psycopg2` codec via a SQLAlchemy `connect` event, or embedding columns read back as raw text instead of `list[float]`.

## Sources

- Codebase Index — `docs/codebase/000-index.md`
- Database Access Strategy — `docs/codebase/004-database.md`
- Second Brain — Ticket 1: Infrastructure & Foundation Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-1-infrastructure.md`
- Fix `just test-integration` Implementation Plan — `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`
- Second Brain — System Design Spec — `docs/superpowers/specs/2026-06-16-second-brain-design.md`
- Spec: Fix `just test-integration` failures (4 independent root causes) — `docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md`

## Related Topics

- [[database-access-patterns]]
- [[pgvector-embeddings]]
- [[postgres-connection-pooling]]
- [[second-brain-architecture]]
- [[memory-system]]
- [[document-ingestion-pipeline]]
- [[integration-testing]]
- [[infrastructure-setup]]
- [[codebase-overview]]
- [[asyncpg-jsonb-codec]]
- [[database-migration-container]]
- [[evaluation-harness]]
- [[second-brain-requirements]]
- [[system-architecture]]
