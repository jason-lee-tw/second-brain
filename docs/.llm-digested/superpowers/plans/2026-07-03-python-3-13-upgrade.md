# Python 3.13 Upgrade Implementation Plan

Source: docs/superpowers/plans/2026-07-03-python-3-13-upgrade.md
Primary-Topic: python-3-13-upgrade
Secondary-Topics: uv-dependency-management, docker-backend-image

## Key Concepts

- **Goal**: move the project's Python version from 3.12 to 3.13 across local development and the Docker runtime, with no behavior change. This is a version-pin bump, not a design change.
- **Status**: Done, verified, reviewed. Committed as `32945f5` on branch `config/000-upgrade-python-3-13`, ahead of `origin` — push was pending because a push attempt was denied by a permission prompt and needed a manual push.
- **Execution strategy decision**: executed sequentially rather than via the `autonomous-feature-development` skill's parallel-worktree pipeline, because Task 2 and Task 3 explicitly consume artifacts Task 1 produces (the regenerated `.venv`/`uv.lock`, then the Dockerfile change), and Task 3 mutates shared Docker/Ollama port state — parallel worktree agents would have raced or verified against a stale pre-upgrade environment. This was confirmed with the user before proceeding.
- **Global constraints governing every file change**:
  - `requires-python` bound in both workspace members (`apps/backend`, `apps/eval`) becomes exactly `">=3.13"` — same open-ended lower-bound style as the prior `">=3.12"`.
  - `ruff.toml` `target-version` becomes exactly `"py313"`.
  - Docker base image becomes exactly `python:3.13-slim` — no patch-version pin, matching the existing `python:3.12-slim` convention.
  - New `.python-version` file at repo root must be created via `uv python pin 3.13` (not hand-written), so its content matches what `uv` itself produces.
  - **Hard gate**: if `uv lock` cannot resolve a cp313 wheel for any existing dependency, STOP — report the exact package and error. Do not pin an older sub-dependency, do not pass `--no-binary`, do not skip the package; the upgrade stays blocked until real cp313 support exists.
  - Out of scope: do not touch `docs/superpowers/plans/*` or `docs/superpowers/specs/*` (dated historical records).
  - No CI config exists in this repo, so nothing to update there.
  - Companion spec document: `docs/superpowers/specs/2026-07-03-python-3-13-upgrade-design.md`.
- **Task 1 — Bump version pins and regenerate the toolchain**:
  - Files modified: `apps/backend/pyproject.toml:8` (`requires-python = ">=3.12"` → `">=3.13"`), `apps/eval/pyproject.toml:4` (same change), `ruff.toml:2` (`target-version = "py312"` → `"py313"`), `docker/Dockerfile.backend:1` (`FROM python:3.12-slim` → `FROM python:3.13-slim`), `docs/codebase/001-tech-stack.md:5` (table row text `Python 3.12` → `Python 3.13`), `docs/codebase/003-system-architecture.md:13` (same table-row text swap).
  - New file `.python-version` created via `uv python pin 3.13` (not hand-written).
  - `uv.lock` regenerated via `uv lock`; `.venv` regenerated via `just clean-python && uv sync --all-extras`.
  - Interpreter availability step: `uv python install 3.13` (installs or confirms already installed, exit code 0).
  - Pin step: `uv python pin 3.13` writes `.python-version` containing `3.13`.
  - Hard-gate verification step: `uv lock` resolved 168 packages including all flagged at-risk compiled-wheel packages — `spacy`, `presidio-analyzer`, `presidio-anonymizer`, `psycopg2-binary`, `arize-phoenix-otel`, `langgraph-checkpoint-postgres` — all of which have cp313 wheels, so the hard gate did not trip.
  - Rollback procedure documented for hard-gate failure (not exercised, since it passed): `git checkout -- apps/backend/pyproject.toml apps/eval/pyproject.toml ruff.toml docker/Dockerfile.backend docs/codebase/001-tech-stack.md docs/codebase/003-system-architecture.md`, `rm .python-version`, `uv lock`.
  - Venv rebuild verification: `uv sync --all-extras` installed 164 packages; `uv run python --version` → `Python 3.13.13`.
  - Commit command for Task 1: `git add apps/backend/pyproject.toml apps/eval/pyproject.toml ruff.toml docker/Dockerfile.backend docs/codebase/001-tech-stack.md docs/codebase/003-system-architecture.md .python-version uv.lock` then `git commit -m "config: upgrade Python 3.12 to 3.13"`.
  - Result: all 6 files edited, `.python-version` created, `uv.lock` regenerated; committed as `32945f5`.
- **Task 2 — Local verification suite** (no files change if Task 1 was done correctly; consumes the 3.13 `.venv`/`uv.lock` from Task 1; produces confirmation that lint, format, type-check, and unit tests are green under 3.13 for both `apps/backend` and `apps/eval`, a precondition for Task 3):
  - `just lint` → `All checks passed!`, exit 0.
  - `just format && git status --porcelain` → no diff (codebase was already 3.13-formatting-compatible).
  - `just type-check` → `✅ Type check is completed`, 0 errors/0 warnings from basedpyright.
  - `just test-unit` → 209 passed.
  - `just test-eval` → 90 passed — called out explicitly because `apps/eval`'s `requires-python` was also bumped and shares the same regenerated `.venv`/`uv.lock`, so `just test-unit` alone would not cover it.
  - Failure-handling instructions (not triggered — all steps passed): do not proceed to Task 3; diagnose via `superpowers:systematic-debugging` (a failure here would mean either a 3.13 behavior change, e.g. a stdlib deprecation now an error, or a resolved dependency version changed behavior); fix root cause in application code, re-run the failing command, commit the fix as a new commit (never amend Task 1's commit, per project CLAUDE.md), and never weaken lint/type-check rules to paper over a failure.
- **Task 3 — Docker runtime verification** (no files change; consumes `docker/Dockerfile.backend` from Task 1 and the green suite from Task 2; produces confirmation the containerized backend runs on 3.13 and serves real requests — the final acceptance criterion from the spec):
  - Prerequisite: `apps/backend/.env` must exist and be populated (same as any normal `just up-all` run), and Ollama must be reachable via the existing `ollama-checker` service.
  - `just up-all` → build completes, `db_migration` exits 0, `backend` container reaches running state, uvicorn started on port 8000 with no import/startup errors.
  - `docker compose exec backend python --version` → `Python 3.13.14`.
  - Real query-path exercise: `curl -s -X POST http://localhost:3001/query -H "Content-Type: application/json" -d '{"message": "What is in my second brain?"}'` → HTTP 200 with JSON body containing `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`, `retrievedContexts` (matching `QueryResponse` in `apps/backend/src/second_brain/api/schemas.py`) — not a 500 or connection error.
  - `just down-all` → containers stop cleanly, exit 0.
  - Failure-handling instructions (not triggered — steps 1-3 all passed): do not report the upgrade as done; capture the exact error (build log, container log, or HTTP response) and diagnose via `superpowers:systematic-debugging` before retrying.
- **Review verdict**: `enhanced-review` gave 🟢 Good Taste / ✅ SHIP IT — diff matches spec exactly, the hard gate was genuinely exercised (not theater), no findings.
- **Outstanding item at time of writing**: push commit `32945f5` to `origin/config/000-upgrade-python-3-13` to update PR #16 (open, no CI configured, no review threads).
- **Toolchain/tools referenced**: `uv` (workspace + lockfile + interpreter management), `ruff` (lint/format), `basedpyright` (type check), `pytest` (unit tests), Docker Compose (runtime), `just` (task runner).
- **Agentic-worker note at top of plan**: required sub-skill is `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement the plan task-by-task; steps use checkbox (`- [ ]`) syntax for tracking.
