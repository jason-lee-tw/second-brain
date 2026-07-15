# Python 3.13 Upgrade Design

Source: docs/superpowers/specs/2026-07-03-python-3-13-upgrade-design.md
Primary-Topic: python-version-upgrade
Secondary-Topics: dependency-lockfile-management, docker-image-build

## Key Concepts

- Goal: bump the project's Python version from 3.12 to 3.13 across local development and the Docker runtime — routine toolchain currency, not driven by any dependency requirement or 3.13-only language feature.
- Single approach, no architectural decision: bump every version declaration point, regenerate derived lockfile/venv/image, then verify. Framed explicitly as "a pin bump, not a design decision."
- Hard gate: if `uv lock` cannot resolve a cp313 wheel for any existing dependency, the upgrade is blocked outright. No pinning to an older sub-dependency, no `--no-binary` workaround, no silent skip — must report the specific offending package and stop.
- Dependencies flagged as most likely to have compiled/platform-wheel issues on cp313: `spacy`, `presidio-analyzer`, `presidio-anonymizer`, `psycopg2-binary`, `arize-phoenix-otel`, `langgraph-checkpoint-postgres`.
- Files changed (hand-edited version declaration points):
  - `apps/backend/pyproject.toml`: `requires-python = ">=3.12"` → `">=3.13"`
  - `apps/eval/pyproject.toml`: `requires-python = ">=3.12"` → `">=3.13"`
  - `ruff.toml`: `target-version = "py312"` → `"py313"`
  - `docker/Dockerfile.backend`: `FROM python:3.12-slim` → `FROM python:3.13-slim`
  - `docs/codebase/001-tech-stack.md`: "Python 3.12" → "Python 3.13"
  - `docs/codebase/003-system-architecture.md`: "Python 3.12" → "Python 3.13"
  - `.python-version` (new file, repo root): contains `3.13` — pins local `uv` interpreter selection deterministically; no such file exists today, so local dev currently relies solely on the `requires-python` lower bound.
- Regenerated (not hand-edited) artifacts:
  - `uv.lock` — regenerated via `uv lock` after the `requires-python` bumps.
  - `.venv` — regenerated via `uv python install 3.13` (if not already fetched) then `uv sync --all-extras`; the existing `just clean-python` recipe removes the stale 3.12 venv first.
  - Docker image — rebuilt via `docker compose build backend` / `just up-build`.
- Explicitly out of scope: `docs/superpowers/plans/*` and `docs/superpowers/specs/*` also mention "3.12" but are dated historical records of past decisions — intentionally not touched, since rewriting them would falsify history.
- Risk: the only real risk called out is dependency wheel availability on cp313 (per the hard gate above). Everything else (pyproject bounds, ruff target, Dockerfile base image, docs strings) is described as a mechanical string change with no behavioral ambiguity.
- Verification steps:
  1. `just lint`, `just format`, `just type-check`, `just test-unit` must all pass under the 3.13 venv.
  2. `docker compose build backend` (or `just up-build`) must succeed against the `python:3.13-slim` base image.
  3. `just up-all`, then confirm via `docker exec` that the backend container reports Python 3.13.x, and that `POST /query` returns a real response (not merely "container up").
- Rollback plan: revert the version-string changes and delete `.python-version`; regenerate `uv.lock`/`.venv`/Docker image against 3.12. No data or schema is touched, so rollback is a pure code revert.
- What does NOT change: application source code, `docker-compose.yml`, database schema/migrations, CI (none exists in this repo today), and historical planning docs under `docs/superpowers/plans/` and `docs/superpowers/specs/`.
- Document metadata: dated 2026-07-03, status "Approved".
