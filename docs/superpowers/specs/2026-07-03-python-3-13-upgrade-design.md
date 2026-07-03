# Python 3.13 Upgrade Design

**Date:** 2026-07-03
**Status:** Approved

## Goal

Upgrade the project's Python version from 3.12 to 3.13, across local development and the Docker runtime. Routine toolchain currency — no dependency or 3.13-only language feature is forcing this.

## Approach

Single approach: bump every version declaration point, regenerate the derived lockfile/venv/image, verify. There is no architectural choice here — this is a pin bump, not a design decision.

**Hard gate:** if `uv lock` cannot resolve a cp313 wheel for any existing dependency, the upgrade is blocked. No pinning to an older sub-dependency, no `--no-binary` workaround, no silent skip — report the specific package and stop. The dependencies most likely to be affected are the ones with compiled/platform wheels: `spacy`, `presidio-analyzer`, `presidio-anonymizer`, `psycopg2-binary`, `arize-phoenix-otel`, `langgraph-checkpoint-postgres`.

## Files Changed

| File                                       | Change                                                                                                                                                                 |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/backend/pyproject.toml`              | `requires-python = ">=3.12"` → `">=3.13"`                                                                                                                              |
| `apps/eval/pyproject.toml`                 | `requires-python = ">=3.12"` → `">=3.13"`                                                                                                                              |
| `ruff.toml`                                | `target-version = "py312"` → `"py313"`                                                                                                                                 |
| `docker/Dockerfile.backend`                | `FROM python:3.12-slim` → `FROM python:3.13-slim`                                                                                                                      |
| `docs/codebase/001-tech-stack.md`          | "Python 3.12" → "Python 3.13"                                                                                                                                          |
| `docs/codebase/003-system-architecture.md` | "Python 3.12" → "Python 3.13"                                                                                                                                          |
| `.python-version` (new, repo root)         | `3.13` — pins local `uv` interpreter selection deterministically; no such file exists today, so local dev currently relies solely on the `requires-python` lower bound |

**Regenerated, not hand-edited:**

- `uv.lock` — via `uv lock` after the `requires-python` bumps above
- `.venv` — via `uv python install 3.13` (if not already fetched) then `uv sync --all-extras` (existing `just clean-python` recipe removes the stale 3.12 venv first)
- Docker image — rebuilt via `docker compose build backend` / `just up-build`

**Explicitly out of scope:** `docs/superpowers/plans/*` and `docs/superpowers/specs/*` also mention "3.12" but are dated historical records of past decisions — not touched, since rewriting them would falsify history.

## Risk

The only real risk is dependency wheel availability on cp313 (see Hard gate above). Everything else (pyproject bounds, ruff target, Dockerfile base image, docs) is a mechanical string change with no behavioral ambiguity.

## Verification

1. `just lint`, `just format`, `just type-check`, `just test-unit` — all pass under the 3.13 venv.
2. `docker compose build backend` (or `just up-build`) succeeds against `python:3.13-slim`.
3. `just up-all`, then confirm via `docker exec` that the backend container reports Python 3.13.x, and `POST /query` returns a real response (not just "container up").

## Rollback

Revert the version-string changes and delete `.python-version`; regenerate `uv.lock`/`.venv`/Docker image against 3.12. No data or schema is touched, so rollback is a pure code revert.

## What Does NOT Change

- Application source code
- `docker-compose.yml`
- Database schema / migrations
- CI (none exists in this repo today)
- Historical planning docs under `docs/superpowers/plans/` and `docs/superpowers/specs/`
