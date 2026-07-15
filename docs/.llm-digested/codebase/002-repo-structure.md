# Repo Structure

Source: docs/codebase/002-repo-structure.md
Primary-Topic: repo-structure
Secondary-Topics: backend-architecture, build-and-deployment

## Key Concepts

- Workspace root uses `uv` (Python packaging tool): `pyproject.toml` is the uv workspace root with members `apps/backend` and `apps/eval`; a single `uv.lock` lockfile is shared across the whole workspace.
- `ruff.toml` at the repo root holds shared lint/format config for all workspace members.
- `apps/backend/` is the backend service package, source at `apps/backend/src/second_brain/`:
  - `config.py` — pydantic-settings `Settings` class; validates all env vars at startup.
  - `main.py` — the FastAPI app entrypoint, includes `/health`.
  - `api/routers/` — endpoint routers (query, ingest) — marked planned.
  - `api/schemas.py` — request/response schema definitions.
  - `db/models.py` — all 5 SQLModel table definitions; the source of truth for DB types.
  - `db/session.py` — SQLAlchemy engine plus `get_session` FastAPI dependency.
  - `graphs/` — LangGraph graph definitions (the query graph and the ingestion graph).
  - `nodes/` — LangGraph node implementations used by the graphs.
  - `services/chunking.py` — hybrid document chunking (headings → paragraphs → sentences); planned.
  - `services/embeddings.py` — Ollama embedding client using model `qwen3-embedding:0.6b`; planned.
  - `services/pii.py` — Presidio-based PII redaction; planned.
  - `services/tavily.py` — Tavily web search/crawl client; planned.
  - `observability/tracing.py` — `setup_tracing()` function and `@trace_node` decorator; planned.
- `apps/backend/alembic/` — DB migration tooling; `alembic/versions/` holds migration files, e.g. `001_initial_schema.py`.
- `apps/backend/tests/` — test suite split into `unit/` (no DB required) and `integration/` (migration + DB tests, requires a running Postgres instance).
- `apps/backend/pyproject.toml` — defines the `second-brain` package (runtime + dev dependencies).
- `apps/backend/pytest.ini` — backend pytest config: testpaths, `asyncio_mode`, and `pythonpath` (roots imports at `src/`, e.g. `from second_brain.config import settings`).
- `apps/backend/alembic.ini` — Alembic configuration file for the backend.
- `apps/eval/` is the evaluation-harness package for RAGAS-based evaluation:
  - `pyproject.toml` — defines the `second-brain-eval` package; depends on `ragas` and the `second-brain` workspace package.
  - `dataset/` — curated evaluation Q&A pairs (target size 30–50 after manual curation).
  - `generate_dataset.py` — uses Claude to generate ~100 Q&A pairs from ingested docs; planned.
  - `baseline.py` — a no-RAG baseline that queries Claude only, without retrieval; planned.
  - `run_eval.py` — runs the full RAGAS evaluation; planned.
  - `compare.py` — produces a markdown report comparing RAG vs. baseline with a delta; planned.
- `temp/` holds the file-ingestion pipeline's working directories:
  - `pending-digest-docs/` — drop `.md` files here to be ingested.
  - `processed/` — files are moved here after successful ingestion.
  - `failed/` — files are moved here after 3 ingestion retries are exhausted.
- `docker-compose.yml` at repo root orchestrates the services (backend, DB, Phoenix, etc.).
- `Justfile` at repo root defines the project's `just` task recipes (build/verify commands).
- `docker/` holds Dockerfiles named `Dockerfile.<service>` (e.g. `Dockerfile.backend` for the backend service image) and `ollama-checker.sh`, a script that waits for Ollama to be ready before starting the backend container.
- `scripts/` holds operational shell scripts:
  - `init.sh` — installs git hooks and runs `uv sync --all-extras`.
  - `start-ollama.sh` — starts the Ollama service.
  - `stop-ollama.sh` — stops the Ollama service.
