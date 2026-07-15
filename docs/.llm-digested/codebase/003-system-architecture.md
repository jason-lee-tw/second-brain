# System Architecture

Source: docs/codebase/003-system-architecture.md
Primary-Topic: system-architecture
Secondary-Topics: connection-pooling, observability

## Key Concepts

- Overview: personal "Second Brain" knowledge management system built with FastAPI, LangGraph multi-agent orchestration, PostgreSQL + pgvector, and Arize Phoenix for observability.
- Two independent LangGraph graphs — `SecondBrainState` (query) and `IngestionState` (ingestion) — share the same database but never share runtime state.
- Tech stack table: Python 3.13; FastAPI (web framework); LangGraph (agent orchestration); PostgreSQL + pgvector (Docker) as database; SQLModel + Alembic (ORM + migrations); Arize Phoenix (OTEL) for observability; embedding model `qwen3-embedding:0.6b` via Ollama (localhost:11434, dim=1024); lightweight LLM `claude-haiku-4-5`; synthesis/eval LLM `claude-sonnet-4-6`; Tavily SDK for web search/crawl; Docker Compose for containerisation.
- High-Level Architecture diagram: FastAPI backend at localhost:3001 exposes `POST /query`, `POST /ingest/file`, `POST /ingest/url`.
  - `/query` routes to the Query Graph (`SecondBrainState`).
  - `/ingest/file` and `/ingest/url` route to the Ingestion Graph (`IngestionState`).
  - Both graphs live inside `app_network` alongside `app_postgres`, which holds tables: `chat_history`, `learned_facts + embedding`, `model_corrections + embedding`, `document_chunks (pgvector)`, `ingested_documents`.
  - Both graphs write to `PG` (app_postgres).
  - LangGraph (`LG`) sends traces to Arize Phoenix via OTEL gRPC on host port 4317; Phoenix (`PH`) and its own `phoenix_postgres` (`PPG`) live in a separate, isolated `phoenix_network`.
- Docker Networks: two fully isolated networks — `app_network` (backend + app_postgres) and `phoenix_network` (phoenix + phoenix_postgres). The backend never joins `phoenix_network`; traces reach Phoenix only via gRPC on host port 4317.
  - Linux note: the `backend` service requires `extra_hosts: ["host.docker.internal:host-gateway"]` for this host-port routing to work; Docker Desktop (Mac/Windows) provides this automatically.
- Container Startup Order: `app_postgres` becomes healthy → triggers both `db_migration` (runs `alembic upgrade head`) and `ollama-checker` → `backend` (uvicorn) starts only after both `db_migration` and `ollama-checker` complete successfully.
  - `db_migration` is a one-shot container that reuses the backend image, runs the Alembic upgrade, and exits.
- Connection Pool Architecture: two distinct DB connection pools coexist and cannot be shared because they use different drivers.
  - `asyncpg.Pool` (driver: asyncpg) — used by `rag_retrieval.py` and `memory_retrieval_node` for pgvector queries.
  - `AsyncConnectionPool` (driver: psycopg3) — used by `query_graph.py` for LangGraph's `AsyncPostgresSaver` checkpointing.
  - `db/pool.py` holds the shared asyncpg pool singleton, accessed via `get_pgvector_pool()`.
  - The psycopg3 pool must be constructed with `autocommit=True` so LangGraph's `CREATE INDEX CONCURRENTLY` can run outside a transaction block.
- Database Schema: full schema, ER diagram, and DB access strategy documented separately in `docs/codebase/004-database.md` (linked as `004-database.md` from this source).
- Workspace Structure (monorepo layout):
  - Workspace root `ai-learning-milestone/` contains `pyproject.toml` ([tool.uv.workspace] only), shared `uv.lock`, shared `ruff.toml` lint/format config, and shared `.venv/`.
  - `apps/backend/` — has its own `pyproject.toml` (backend dependencies), `pytest.ini` (test config with `pythonpath = src`), `src/second_brain/` (application source), `tests/` (unit + integration tests), `alembic/` (DB migrations), `alembic.ini`.
  - `apps/eval/` — has its own `pyproject.toml` (ragas + eval deps), `generate_dataset.py`, `run_eval.py`, `compare.py`.
  - `docker/` — contains `Dockerfile.backend` (backend image; build context is `apps/backend/`) and `ollama-checker.sh`.
  - Top-level `docker-compose.yml` and `Justfile`.
- Observability: full distributed tracing via OTEL to Arize Phoenix, at three levels per `/query` request:
  - LLM call level — every prompt/completion, token counts, latency.
  - Agent/node level — which agents ran, order, duration, routing decision.
  - Request level — end-to-end HTTP request → response.
  - `phoenix.otel.register(auto_instrument=True)` activates `openinference-instrumentation-langchain` automatically — no separate instrumentor call is needed.
  - Phoenix UI is served at `localhost:6006`; traces are stored in the isolated `phoenix_postgres` database.
- API Surface table:
  - `POST /query` — chat with the Second Brain.
  - `POST /ingest/file` — process pending `.md` files from `temp/pending-digest-docs/`.
  - `POST /ingest/url` — receive URL(s), crawl via Tavily, ingest as markdown.
