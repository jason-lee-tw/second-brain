# Workspace Restructure Design

Source: docs/superpowers/specs/2026-06-17-workspace-restructure-design.md
Primary-Topic: uv-workspace-restructure
Secondary-Topics: justfile-build-recipes, python-tooling-configuration

## Key Concepts

- Design dated 2026-06-17, status Approved.
- Goal: convert the project from a single backend-only `pyproject.toml` to a uv workspace with a thin root container, a shared root `.venv`, and two workspace members: `apps/backend` and `apps/eval`.
- Approach chosen: "uv workspace, thin root" (Option A) — root `pyproject.toml` contains only `[tool.uv.workspace]`, no `[project]` section.
- A single `uv.lock` and a single `.venv` live at the project root (previously these lived under `apps/backend/`).
- Tool configs move out of inline `[tool.*]` sections in `pyproject.toml` into dedicated files — e.g. `ruff.toml` at the root.
- Pytest config moves from `pyproject.toml`'s `[tool.pytest.ini_options]` into per-member `pytest.ini` files (e.g. `apps/backend/pytest.ini`).
- Directory structure changes:
  - Root gets: `pyproject.toml` (workspace-only), `uv.lock` (moved from `apps/backend/`), `ruff.toml` (new, shared config), `.venv/` (moved from `apps/backend/.venv`, shared across workspace).
  - `apps/backend/`: `pyproject.toml` updated (removes `[tool.ruff]`, `[tool.pytest.ini_options]`, and the `eval` optional-dependency group); adds `pytest.ini`; deletes its own `uv.lock` and `.venv/`; `src/`, `tests/`, `alembic/`, `alembic.ini` unchanged.
  - `apps/eval/` is new, moved from a root-level `eval/` directory: gets its own `pyproject.toml` (owns `ragas` + eval deps), and moved scripts `generate_dataset.py`, `baseline.py`, `run_eval.py`, `compare.py`, and the `dataset/` folder.
  - `scripts/init.sh` unchanged (uv sync already runs from root).
  - `Justfile` updated to add lint/format targets and update test targets.
  - `.gitignore` unchanged (already ignores `.venv`).
- Root `pyproject.toml` content: `[tool.uv.workspace]` with `members = ["apps/backend", "apps/eval"]`.
- `ruff.toml` (root) content: `line-length = 88`, `target-version = "py312"`, `[lint] select = ["E", "F", "I"]`, `[format] quote-style = "double"`.
- `apps/backend/pytest.ini` content: `[pytest]` section with `testpaths = tests`, `asyncio_mode = auto`, `pythonpath = src`.
- `apps/backend/pyproject.toml` changes: remove `[tool.pytest.ini_options]` (replaced by `pytest.ini`); remove `[project.optional-dependencies] eval` group (moves to `apps/eval/pyproject.toml`); all runtime and dev dependencies unchanged.
- `apps/eval/pyproject.toml` content: build-system `hatchling`; `[project]` name `second-brain-eval`, version `0.1.0`, `requires-python = ">=3.12"`, dependencies `ragas>=0.2.0` and `second-brain`.
- `"second-brain"` dependency in `apps/eval` is resolved as a uv workspace cross-reference, linking to `apps/backend/` without path hacks.
- Justfile new/updated recipes (grouped under "Format" and "Test" and "DB"):
  - `lint`: `ruff check .`
  - `format`: `ruff format .`
  - `test-unit`: `uv run --package second-brain pytest apps/backend/tests/unit`
  - `test-integration`: `uv run --package second-brain pytest apps/backend/tests/integration`
  - `test`: `uv run --package second-brain pytest apps/backend/tests`
  - `migrate`: `cd apps/backend && uv run alembic upgrade head`
- Developer workflow before/after table:
  - Install deps: before `cd apps/backend && uv sync`, after `uv sync` from root.
  - Run backend tests: before `cd apps/backend && pytest`, after `just test-unit`.
  - Lint/format: before not wired up, after `just lint` / `just format`.
  - Alembic migrations: before `cd apps/backend && alembic ...`, after `just migrate`.
  - Run eval scripts: before `cd eval && python run_eval.py`, after `cd apps/eval && uv run python run_eval.py`.
  - Docker: unchanged, `just up-build` both before and after.
- Explicitly listed as NOT changing: Docker build context (`apps/backend/`) though the `Dockerfile` itself relocates to `docker/Dockerfile.backend`; `alembic.ini` location and all alembic commands (still run from `apps/backend/`); `.env` file location (`apps/backend/.env`); all application source code; `docker-compose.yml`; `scripts/init.sh`.
