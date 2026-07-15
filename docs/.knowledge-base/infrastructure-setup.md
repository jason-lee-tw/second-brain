# Infrastructure Setup

Ticket 1 built the Second Brain project's foundation — Docker services, the FastAPI/SQLModel backend skeleton, and the first Alembic migration — so that `docker compose up` starts everything, all 5 tables exist with the correct schema, and `GET /health` returns 200.

## Key Concepts

- **Scope**: set up Docker infrastructure, a FastAPI skeleton, all SQLModel DB models, and Alembic migrations in one ticket, executed task-by-task via `superpowers:subagent-driven-development`/`superpowers:executing-plans` with checkbox tracking.
- **Network isolation boundary**: backend and its Postgres (`app_postgres`) share `app_network`; Phoenix and its own Postgres (`phoenix_postgres`) share an isolated `phoenix_network`. The backend container never joins `phoenix_network` directly — it reaches Phoenix only via host port 6006, using `host.docker.internal`. This is a deliberate security boundary, not an oversight.
- **Schema ownership**: the DB schema is managed exclusively through Alembic migrations; SQLModel models double as both the ORM table definitions and the source-of-truth type definitions referenced by every later ticket.
- **Initial tech stack pinned by this ticket**: Python 3.12, FastAPI, SQLModel, PostgreSQL 16 + pgvector, Alembic, pydantic-settings, Docker Compose, Arize Phoenix, pytest.

### Docker infrastructure (Task 1)

- Services defined in `docker-compose.yml`: `ollama-checker` (host network, checks Ollama reachability before backend starts), `app_postgres` (`pgvector/pgvector:pg16`, db/user/password `second_brain`/`second_brain`/`secret`, healthcheck `pg_isready`), `phoenix_postgres` (`postgres:16`, db/user/password `phoenix`/`phoenix`/`phoenix_secret`), `phoenix` (`arizephoenix/phoenix:latest`, port 6006), and `backend` (build context `./apps/backend`, port 8000, depends on `app_postgres` healthy and `ollama-checker` completed successfully).
- `pgvector/pgvector:pg16` ships the pgvector shared library pre-installed, but the `vector` extension must still be enabled per-database via `CREATE EXTENSION IF NOT EXISTS vector` — done inside the first Alembic migration, not in Compose.
- `backend` and `ollama-checker` both set `extra_hosts: host.docker.internal:host-gateway` so they can resolve the host from inside Docker on Linux (Docker Desktop on Mac/Windows resolves this automatically).
- `.env.template` documents: `OLLAMA_BASE_URL`, `DATABASE_URL` (using the `app_postgres` service name as hostname), `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, and `PHOENIX_COLLECTION_ENDPOINT` (pointed at the host, never at `phoenix_network`). The real `.env` is gitignored, created via `cp apps/backend/.env.template apps/backend/.env`.
- `temp/pending-digest-docs/`, `temp/processed/`, `temp/failed/` are created with `.gitkeep` files for the later file-ingestion endpoints.
- Verification: bring up `app_postgres`, `phoenix_postgres`, `phoenix` and expect all healthy within ~30s; confirm the `vector` extension is *available* (not yet enabled) via `pg_available_extensions`; confirm Phoenix UI returns HTTP 200 on `localhost:6006`.

### Python project bootstrap (Task 2)

- `pyproject.toml` (hatchling backend, `requires-python = ">=3.12"`) pins runtime deps including fastapi, uvicorn, sqlmodel, alembic, psycopg2-binary, pgvector, pydantic-settings, langchain-anthropic, langgraph, anthropic, tavily-python, the OpenTelemetry/Arize Phoenix OTEL stack, and presidio + spacy for PII scrubbing. Optional groups: `dev` (pytest, pytest-asyncio, httpx) and `eval` (ragas).
- `[tool.pytest.ini_options]` sets `pythonpath = ["src"]` — the mechanism that lets tests import as `from second_brain...` rooted at `src/`.
- The backend `Dockerfile` (originally at `apps/backend/Dockerfile`, later consolidated — see [[dockerfile-consolidation]]) is based on `python:3.12-slim` (later upgraded — see [[python-3-13-upgrade]]), installs `gcc`/`libpq-dev`/`curl`, copies `pyproject.toml` first to leverage Docker layer caching before `pip install -e .`, and downloads the `en_core_web_lg` spacy model (~500MB, slow build step) required by presidio.
- Package skeleton created under `apps/backend/src/second_brain/{api/routers, db, graphs, nodes, services, observability}`.

### Config module and health check (Task 3, TDD)

- `tests/conftest.py` sets required env vars via `os.environ.setdefault(...)` before any `second_brain` import, since pydantic-settings reads env vars at `Settings()` instantiation.
- `config.py` defines a `Settings(BaseSettings)` with `database_url`, `ollama_base_url`, `anthropic_api_key`, `tavily_api_key`, `phoenix_collection_endpoint`, loaded from `.env`, exposed as a module-level `settings` singleton.
- `main.py` imports `settings` at startup (fail-fast if env vars are missing) and exposes `GET /health` returning `{"status": "ok"}`.

### Database models (Task 4, TDD)

- All 5 SQLModel `table=True` classes live in `db/models.py`: `ChatHistory` (`chat_history`, PK `session_id: str` doubling as the LangGraph `thread_id`, JSONB `thread_data`), `IngestedDocument` (`ingested_documents`, dedup via `content_hash`, `status: 'processed'|'failed'`), `DocumentChunk` (`document_chunks`, FK to `ingested_documents.id`, `embedding: Vector(1024)`), `LearnedFact` (`learned_facts`, FK `source_session` to `chat_history.session_id`, `embedding: Vector(1024)`), `ModelCorrection` (`model_corrections`, FK `source_session` to `chat_history.session_id`, `embedding: Vector(1024)`).
- Naming note: `DocumentChunk`'s Python attribute is `chunk_metadata`, mapped via `sa_column=Column("metadata", JSONB, ...)` to the SQL column `metadata` — this avoids shadowing SQLModel/SQLAlchemy's class-level `metadata` attribute. It is documented as the *only* deliberate divergence from the spec's field names.
- `ModelCorrection.embedding` encodes the `correction` field, not `original_answer` — so cosine-similarity retrieval surfaces the correct answer rather than the original mistake.
- `db/session.py` provides `engine = create_engine(settings.database_url)` and a `get_session()` FastAPI dependency generator.
- Expected outcome: 11 model unit tests + 2 health tests = 13 unit tests passing.

### Alembic setup and first migration (Task 5)

- `alembic/env.py` adds `apps/backend/src` to `sys.path`, imports `second_brain.db.models` for its metadata-registration side effect, and overrides `sqlalchemy.url` from `settings.database_url` at runtime — `alembic.ini`'s own `sqlalchemy.url` is just a placeholder so the file parses.
- The first migration (`001_initial_schema`, `down_revision = None`) runs `CREATE EXTENSION IF NOT EXISTS vector` before creating any table, then creates all 5 tables in dependency order (`chat_history` → `ingested_documents` → `document_chunks` → `learned_facts` → `model_corrections`); `downgrade()` reverses the order and drops the extension last.
- Verification: `alembic upgrade head` against a live `DATABASE_URL`, 9 integration tests asserting table/column/FK shape, then `alembic check` reporting "No new upgrade operations detected." to confirm models and migration are in sync.

### End-to-end verification (Task 6)

- `docker compose up -d --build`, then confirm `app_postgres`/`phoenix_postgres` healthy, `phoenix`/`backend` running, `ollama-checker` exited(0); `GET /health` returns `{"status":"ok"}`; `\dt` inside `app_postgres` lists all 5 tables; the `vector` extension row exists in `pg_extension`; all 13 unit tests pass.
- Ticket "done" criteria: `docker compose up` starts all services without errors, all 5 tables exist with correct schema, `/health` returns 200, `alembic upgrade head` runs cleanly inside the backend container, and all unit tests pass.

## Sources

- Second Brain — Ticket 1: Infrastructure & Foundation Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-1-infrastructure.md`

## Related Topics

- [[docker-compose]]
- [[database-migration-container]]
- [[dockerfile-consolidation]]
- [[database-schema]]
- [[tech-stack]]
- [[dependency-management]]
- [[repo-structure]]
- [[implementation-plan]]
- [[python-3-13-upgrade]]
