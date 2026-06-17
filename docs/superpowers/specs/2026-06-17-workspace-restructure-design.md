# Workspace Restructure Design

**Date:** 2026-06-17
**Status:** Approved

## Goal

Convert the project from a single backend-only `pyproject.toml` to a uv workspace with a thin root container, a shared root `.venv`, and two workspace members: `apps/backend` and `apps/eval`.

## Approach

**uv workspace, thin root (Option A).** Root `pyproject.toml` contains only `[tool.uv.workspace]` — no `[project]` section. A single `uv.lock` and `.venv` live at the project root. Tool configs move to dedicated files (`ruff.toml`) rather than inline `[tool.*]` sections in `pyproject.toml`. Pytest config moves to per-member `pytest.ini` files.

## Directory Structure

```
ai-learning-milestone/          (workspace root)
  pyproject.toml                ← NEW: [tool.uv.workspace] only
  uv.lock                       ← MOVED from apps/backend/
  ruff.toml                     ← NEW: shared ruff config
  .venv/                        ← MOVED from apps/backend/.venv (shared workspace venv)
  apps/
    backend/
      pyproject.toml            ← UPDATED: remove [tool.ruff], [tool.pytest.ini_options], eval optional-dep group
      pytest.ini                ← NEW: backend pytest config (moved from pyproject)
      uv.lock                   ← DELETED
      .venv/                    ← DELETED
      src/, tests/, alembic/    ← unchanged
      alembic.ini               ← unchanged
    eval/                       ← NEW: moved from root eval/
      pyproject.toml            ← NEW: workspace member owning ragas + eval deps
      generate_dataset.py       ← MOVED from eval/
      baseline.py               ← MOVED
      run_eval.py               ← MOVED
      compare.py                ← MOVED
      dataset/                  ← MOVED
  scripts/init.sh               ← unchanged (uv sync already runs from root)
  Justfile                      ← UPDATED: add lint/format targets, update test targets
  .gitignore                    ← unchanged (already ignores .venv)
```

## File Contents

### Root `pyproject.toml`

```toml
[tool.uv.workspace]
members = ["apps/backend", "apps/eval"]
```

### `ruff.toml` (root)

```toml
line-length = 88
target-version = "py312"

[lint]
select = ["E", "F", "I"]

[format]
quote-style = "double"
```

### `apps/backend/pytest.ini`

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
pythonpath = src
```

### `apps/backend/pyproject.toml` changes

- Remove `[tool.pytest.ini_options]` section → replaced by `pytest.ini`
- Remove `[project.optional-dependencies] eval` group → moves to `apps/eval/pyproject.toml`
- All runtime and dev dependencies unchanged

### `apps/eval/pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "second-brain-eval"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "ragas>=0.2.0",
    "second-brain",
]
```

`"second-brain"` is resolved as a workspace cross-reference — uv links it to `apps/backend/` without path hacks.

## Justfile Changes

New and updated recipes:

```just
[group: "Format"]
lint:
  @ruff check .

[group: "Format"]
format:
  @ruff format .

[group: "Test"]
test-unit:
  @uv run --package second-brain pytest apps/backend/tests/unit

[group: "Test"]
test-integration:
  @uv run --package second-brain pytest apps/backend/tests/integration

[group: "Test"]
test:
  @uv run --package second-brain pytest apps/backend/tests

[group: "DB"]
migrate:
  @cd apps/backend && uv run alembic upgrade head
```

## Developer Workflow

| Task | Before | After |
|------|--------|-------|
| Install deps | `cd apps/backend && uv sync` | `uv sync` from root |
| Run backend tests | `cd apps/backend && pytest` | `just test-unit` |
| Lint/format | not wired up | `just lint` / `just format` |
| Alembic migrations | `cd apps/backend && alembic ...` | `just migrate` |
| Run eval scripts | `cd eval && python run_eval.py` | `cd apps/eval && uv run python run_eval.py` |
| Docker | `just up-build` | `just up-build` (unchanged) |

## What Does NOT Change

- Docker build context (`apps/backend/`) — `Dockerfile` relocated to `docker/Dockerfile.backend`
- `alembic.ini` location and all alembic commands (still run from `apps/backend/`)
- `.env` file location (`apps/backend/.env`)
- All application source code
- `docker-compose.yml`
- `scripts/init.sh`
