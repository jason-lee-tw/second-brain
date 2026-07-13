# DB Migration Container Implementation Plan

Source: docs/superpowers/plans/2026-06-17-db-migration-container.md
Primary-Topic: database-migration
Secondary-Topics: docker-compose

## Key Concepts

- Goal: add a `db_migration` Docker Compose service that runs `alembic upgrade head` and exits before the `backend` service starts, so schema migrations are applied automatically before the app boots.
- Architecture: the new `db_migration` service builds from the same `Dockerfile.backend` image as `backend` — no new Dockerfile or application source code is required. It only overrides the container `command` to `alembic upgrade head`.
- The service is wired into `backend`'s startup ordering via Docker Compose's `depends_on` with condition `service_completed_successfully` — Compose will not start `backend` until `db_migration` has run to completion and exited with code 0.
- File touched: `docker-compose.yml` only (single-file change).
- Existing services in `docker-compose.yml` before this change: `ollama-checker`, `app_postgres`, `phoenix_postgres`, `phoenix`, `backend`.
- New `db_migration` service block (inserted between `phoenix` and `backend`):
  - `build.context: ./apps/backend`, `build.dockerfile: ../../docker/Dockerfile.backend` (same build context/Dockerfile pattern as `backend`).
  - `command: alembic upgrade head` (overrides the backend's default startup command).
  - `env_file: ./apps/backend/.env` (same env file as backend, so it has DB connection settings).
  - `networks: [app_network]`.
  - `depends_on: app_postgres` with `condition: service_healthy` — migration container must wait for Postgres to be healthy before running alembic.
- `backend.depends_on` is updated to add `db_migration` with `condition: service_completed_successfully`, alongside the pre-existing `app_postgres` (`service_healthy`) and `ollama-checker` (`service_completed_successfully`) dependencies.
- Verification step 1 (static): `docker compose -f docker-compose.yml config --quiet` should produce no output and exit 0 — validates YAML/compose syntax after the edit.
- Verification step 2 (runtime): run `just up-build`, then confirm in Compose logs that `db_migration` logs appear before `backend` startup logs, `db_migration` exits with code 0, and `backend` starts successfully with no "relation does not exist" errors (which would indicate migrations didn't run before backend connected).
- Verification step 3: `curl -s http://localhost:3001/health` should return `{"status": "ok"}`, confirming backend is up and functioning after migrations ran.
- Verification step 4: tear down with `just down`.
- Commit convention used in the plan: `git add docker-compose.yml` then `git commit -m "feat: add db_migration service to run alembic migrations before backend starts"`.
- Plan is written for agentic execution using the `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` skill, with checkbox (`- [ ]`) task tracking for each step.
- No new Dockerfile, no new source code, no changes to Alembic migration scripts themselves — this plan is purely about Docker Compose orchestration/sequencing of an existing `alembic upgrade head` capability.
