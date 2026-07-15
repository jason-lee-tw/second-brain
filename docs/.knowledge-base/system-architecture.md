# System Architecture

The Second Brain's high-level architecture — API surface, two isolated Docker networks, container startup order, the dual connection-pool design, the monorepo workspace layout, and three-level OTEL/Phoenix observability.

## Key Concepts

- **Overview**: a personal "Second Brain" knowledge management system built on FastAPI, LangGraph multi-agent orchestration, PostgreSQL + pgvector, and Arize Phoenix for observability.
- **Two independent LangGraph graphs**: `SecondBrainState` (query) and `IngestionState` (ingestion) share the same `app_postgres` database but never share runtime state — kept as separate state schemas deliberately, to keep each schema clean. See [[query-graph]] and [[document-ingestion-pipeline]] for each graph's internals.
- **Tech stack** (see [[tech-stack]] for the full reference table): Python 3.13; FastAPI; LangGraph; PostgreSQL + pgvector (Docker); SQLModel + Alembic; Arize Phoenix (OTEL); embedding model `qwen3-embedding:0.6b` via Ollama (`localhost:11434`, dim=1024); lightweight LLM `claude-haiku-4-5`; synthesis/eval LLM `claude-sonnet-4-6`; Tavily SDK; Docker Compose.

## API Surface and Request Routing

- `POST /query` — chat with the Second Brain; routes to the Query Graph (`SecondBrainState`).
- `POST /ingest/file` — processes pending `.md` files from `temp/pending-digest-docs/`; routes to the Ingestion Graph (`IngestionState`).
- `POST /ingest/url` — receives URL(s), crawls via Tavily, ingests the result as markdown; also routes to the Ingestion Graph.
- Both graphs run inside `app_network` alongside `app_postgres`, which holds `chat_history`, `learned_facts` + embedding, `model_corrections` + embedding, `document_chunks` (pgvector), and `ingested_documents` — full column-level detail on [[database-schema]].

## Docker Networks and Startup Order

- Two fully isolated Docker networks: `app_network` (backend + `app_postgres`) and `phoenix_network` (Phoenix + `phoenix_postgres`). The backend never joins `phoenix_network` — it reaches Phoenix only via OTLP gRPC on host port 4317, and the Phoenix UI is served separately at `localhost:6006`. This isolation is intentional: in production the backend must never have direct network access to Phoenix or its database.
- Linux Docker hosts need `extra_hosts: ["host.docker.internal:host-gateway"]` on the `backend` service for this host-port routing to work; Docker Desktop (Mac/Windows) provides the mapping automatically.
- Container startup order: `app_postgres` becomes healthy → triggers both `db_migration` (runs `alembic upgrade head`) and `ollama-checker` in parallel → `backend` (uvicorn) starts only after both `db_migration` and `ollama-checker` complete successfully. `db_migration` is a one-shot container that reuses the backend image, runs the Alembic upgrade, and exits — see [[database-migration-container]] for the full fail-closed sequencing design. See [[docker-compose]] for the complete service inventory.

## Connection Pool Architecture

Two distinct DB connection pools coexist and cannot be shared, because they use different drivers:

- `asyncpg.Pool` (asyncpg driver) — used by `rag_retrieval.py` and `memory_retrieval_node` for pgvector cosine-similarity queries. The shared singleton lives in `db/pool.py`, accessed via `get_pgvector_pool()`.
- `AsyncConnectionPool` (psycopg3 driver) — used by `query_graph.py` for LangGraph's `AsyncPostgresSaver` checkpointing. Must be constructed with `autocommit=True` so LangGraph's `CREATE INDEX CONCURRENTLY` can run outside a transaction block.

Full driver-default gotchas (autocommit, JSONB decoding) and the P0 bug this caused are documented on [[postgres-connection-pooling]] rather than repeated here.

## Workspace Structure

Monorepo layout (full annotated tree on [[repo-structure]]):

- Workspace root `ai-learning-milestone/` — `pyproject.toml` (`[tool.uv.workspace]` only), shared `uv.lock`, shared `ruff.toml`, shared `.venv/`.
- `apps/backend/` — own `pyproject.toml`, `pytest.ini` (`pythonpath = src`), `src/second_brain/` application source, `tests/` (unit + integration), `alembic/` migrations, `alembic.ini`.
- `apps/eval/` — own `pyproject.toml` (ragas + eval deps), `generate_dataset.py`, `run_eval.py`, `compare.py`.
- `docker/` — `Dockerfile.backend` (build context is `apps/backend/`) and `ollama-checker.sh`.
- Top-level `docker-compose.yml` and `Justfile`.
- `docs/codebase/000-index.md` is the table-of-contents for this architecture doc plus the tech-stack, repo-structure, and database sub-documents — the authoritative starting point for locating architecture/repo-layout/schema documentation rather than searching the codebase directly.

## Observability

Full distributed tracing via OTEL to Arize Phoenix, at three levels per `/query` request:

- LLM call level — every prompt/completion, token counts, latency.
- Agent/node level — which agents ran, order, duration, routing decision.
- Request level — end-to-end HTTP request → response.

`phoenix.otel.register(auto_instrument=True)` activates `openinference-instrumentation-langchain` automatically — no separate instrumentor call is needed. The Phoenix UI is served at `localhost:6006`; traces are stored in the isolated `phoenix_postgres` database. Full setup flow, instrumentation caveats, and the LangChain/LangGraph span fix on [[otel-phoenix-tracing]].

## Sources

- System Architecture — `docs/codebase/003-system-architecture.md`
- Codebase Index — `docs/codebase/000-index.md`
- Repo Structure — `docs/codebase/002-repo-structure.md`

## Related Topics

- [[codebase-overview]]
- [[repo-structure]]
- [[tech-stack]]
- [[database-schema]]
- [[postgres-connection-pooling]]
- [[otel-phoenix-tracing]]
- [[docker-compose]]
- [[database-migration-container]]
- [[second-brain-architecture]]
- [[query-graph]]
