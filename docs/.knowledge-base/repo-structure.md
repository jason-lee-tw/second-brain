# Repo Structure

The project is a `uv` workspace with a thin root container and two members, `apps/backend` and `apps/eval`, plus root-level `docker/`, `docs/`, `scripts/`, and `temp/` directories.

## Key Concepts

- **Workspace root**: `pyproject.toml` at the repo root declares `[tool.uv.workspace]` with `members = ["apps/backend", "apps/eval"]` and has no `[project]` section — the root itself is not an installable package. A single `uv.lock` and a single shared `.venv/` live at the project root, covering all workspace members (no per-member lockfiles or venvs). `ruff.toml` at the root holds shared lint/format config for the whole workspace.
- **`apps/backend/`** — the backend service package, source at `apps/backend/src/second_brain/`:
  - `config.py` — pydantic-settings `Settings` class; validates all env vars at startup.
  - `main.py` — FastAPI app entrypoint, includes `/health`.
  - `api/routers/` — endpoint routers (query, ingest).
  - `api/schemas.py` — request/response schema definitions.
  - `db/models.py` — all 5 SQLModel table definitions; source of truth for DB types.
  - `db/session.py` — SQLAlchemy engine plus `get_session` FastAPI dependency.
  - `graphs/` — LangGraph graph definitions (query graph and ingestion graph).
  - `nodes/` — LangGraph node implementations used by the graphs.
  - `services/` — chunking, embeddings (Ollama `qwen3-embedding:0.6b`), PII redaction (Presidio), Tavily web search/crawl client.
  - `observability/tracing.py` — `setup_tracing()` and `@trace_node` decorator.
  - `alembic/` — DB migration tooling (`alembic/versions/` holds migration files, e.g. `001_initial_schema.py`); `alembic.ini` configures Alembic.
  - `tests/` — split into `unit/` (no DB required) and `integration/` (migration + DB tests, requires a running Postgres instance).
  - `pyproject.toml` — defines the `second-brain` package (runtime + dev dependencies); no longer carries `[tool.ruff]` or `[tool.pytest.ini_options]` (moved to root `ruff.toml` and local `pytest.ini`), and no longer carries the `eval` optional-dependency group (moved to `apps/eval/pyproject.toml`).
  - `pytest.ini` — `testpaths = tests`, `asyncio_mode = auto`, `pythonpath = src` (roots imports at `src/`, e.g. `from second_brain.config import settings`).
- **`apps/eval/`** — the RAGAS evaluation-harness package:
  - `pyproject.toml` — defines the `second-brain-eval` package; depends on `ragas>=0.2.0` and `second-brain` (resolved as an intra-workspace cross-reference to `apps/backend/`, no path hacks); sets `[tool.uv] package = false` since it's a virtual, scripts-only member with no installable wheel.
  - `dataset/` — curated evaluation Q&A pairs (target 30–50 after manual curation); moved here from a former root-level `eval/` directory via `git mv eval/dataset apps/eval/dataset`.
  - `generate_dataset.py`, `baseline.py` (no-RAG baseline), `run_eval.py`, `compare.py`.
- **`docker/`** — canonical home for all Docker artifacts, named `Dockerfile.<service>` (e.g. `Dockerfile.backend` for the backend image) plus `ollama-checker.sh` (waits for Ollama readiness before starting the backend container). `Dockerfile.backend` was relocated here from `apps/backend/Dockerfile`; each service's Docker build context still remains its own app directory (`apps/<service>/`) so `COPY` instructions inside the Dockerfile stay valid unmodified.
- **`temp/`** — file-ingestion pipeline working directories: `pending-digest-docs/` (drop `.md` files here to be ingested), `processed/` (moved here after successful ingestion), `failed/` (moved here after 3 ingestion retries are exhausted).
- **`scripts/`** — operational shell scripts: `init.sh` (installs git hooks, runs `uv sync --all-extras` from root), `start-ollama.sh`, `stop-ollama.sh`.
- **Root files**: `docker-compose.yml` orchestrates the services (backend, DB, Phoenix, etc.) — its backend `build.dockerfile` field points at `../../docker/Dockerfile.backend`, relative to the unchanged build context `./apps/backend`. `Justfile` defines workspace-aware `just` recipes (e.g. `lint`/`format` run across the whole workspace; `test-unit`/`test-integration`/`test` scope pytest to `apps/backend/tests/...` via `uv run --package second-brain`; `migrate` still `cd`s into `apps/backend` for Alembic).

## Sources

- Repo Structure — `docs/codebase/002-repo-structure.md`
- Dockerfile Consolidation Implementation Plan — `docs/superpowers/plans/2026-06-17-dockerfile-consolidation.md`
- Workspace Restructure Implementation Plan — `docs/superpowers/plans/2026-06-17-workspace-restructure.md`
- Dockerfile Consolidation Design — `docs/superpowers/specs/2026-06-17-dockerfile-consolidation-design.md`
- Workspace Restructure Design — `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md`

## Related Topics

- [[dockerfile-consolidation]]
- [[uv-workspace-restructure]]
- [[codebase-overview]]
- [[tech-stack]]
- [[dependency-management]]
- [[docker-compose]]
- [[infrastructure-setup]]
- [[system-architecture]]
