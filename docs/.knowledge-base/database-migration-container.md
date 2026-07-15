# Database Migration Container

A one-shot `db_migration` Docker Compose service runs `alembic upgrade head` and must exit successfully before `backend` starts, so schema migrations apply automatically on every startup instead of as a manual step.

## Key Concepts

- **Problem**: `just up-build` previously started `backend` without first running database migrations. On a fresh environment with no volumes, `backend` came up against an empty schema and any DB operation failed, because migrations were a separate manual step rather than a startup prerequisite.
- **Goal**: guarantee `alembic upgrade head` completes successfully before `backend` starts, using Docker Compose's native dependency ordering — not a manual/external step.
- **Approach**: add a new `db_migration` service to `docker-compose.yml`. It reuses the existing `backend` image/build context (`Dockerfile.backend`) — no new Dockerfile and no new application source code — and only overrides the container `command` to `alembic upgrade head`. It is a one-shot job, not a long-running service, and is expected to exit.
- **File touched**: `docker-compose.yml` only (single-file change). Existing services before the change: `ollama-checker`, `app_postgres`, `phoenix_postgres`, `phoenix`, `backend`. The new `db_migration` service block is inserted between `phoenix` and `backend`.
- **`db_migration` service definition**:
  - `build.context: ./apps/backend`, `build.dockerfile: ../../docker/Dockerfile.backend` — same build context/Dockerfile pattern as `backend`.
  - `command: alembic upgrade head` — overrides the backend image's default startup command.
  - `env_file: ./apps/backend/.env` — same env file as `backend`, so it has DB connection settings.
  - `networks: [app_network]`.
  - `depends_on: { app_postgres: { condition: service_healthy } }` — migration container waits for Postgres to be healthy before running alembic.
- **Startup order** (Docker Compose dependency graph):
  1. `app_postgres` must reach `healthy` status.
  2. `db_migration` then runs and must exit 0 (`service_completed_successfully`).
  3. `backend` then starts uvicorn.
  - `ollama-checker` runs in parallel with `db_migration` (not sequentially dependent on it); `backend` waits for both to complete successfully.
- **`backend.depends_on` update**: adds `db_migration` with `condition: service_completed_successfully`, alongside the pre-existing `app_postgres` (`service_healthy`) and `ollama-checker` (`service_completed_successfully`) dependencies. Final block: `app_postgres: { condition: service_healthy }`, `db_migration: { condition: service_completed_successfully }`, `ollama-checker: { condition: service_completed_successfully }`.
- **Alembic wiring already in place**: `alembic.ini` sets `script_location = alembic`; `alembic/env.py` overrides the DB URL from `settings.database_url` (sourced from `.env`) — so no extra configuration is needed inside the `db_migration` container beyond what already exists for `backend`.
- **Error handling**: if `alembic upgrade head` exits non-zero, Compose marks `db_migration` as `service_completed_unsuccessfully`, which blocks `backend` from starting at all — failure is fail-closed, not silently ignored. No restart policy is set on `db_migration`; it is intentionally a one-shot job, since automatically retrying a failed migration would just hit the same error again (migrations are not safe to blindly retry without investigation).
- **`just migrate` unchanged**: the Justfile target for running migrations directly on the host (outside Docker) remains a separate manual path for local dev, untouched by this design.
- **Scope boundary**: no new Dockerfile, no new source code, and no changes to Alembic migration scripts themselves — purely Docker Compose orchestration/sequencing of an existing `alembic upgrade head` capability.

## Verification

- Static: `docker compose -f docker-compose.yml config --quiet` should produce no output and exit 0 — validates YAML/compose syntax after the edit.
- Runtime: run `just up-build`, then confirm in Compose logs that `db_migration` logs appear before `backend` startup logs, `db_migration` exits with code 0, and `backend` starts successfully with no "relation does not exist" errors (which would indicate migrations didn't run before backend connected).
- `curl -s http://localhost:3001/health` should return `{"status": "ok"}`, confirming backend is up and functioning after migrations ran.
- Tear down with `just down`.
- Commit convention used in the plan: `git add docker-compose.yml` then `git commit -m "feat: add db_migration service to run alembic migrations before backend starts"`.

## Sources

- [DB Migration Container Implementation Plan] — `docs/superpowers/plans/2026-06-17-db-migration-container.md`
- [DB Migration Container Design] — `docs/superpowers/specs/2026-06-17-db-migration-container-design.md`

## Related Topics

- [[docker-compose]]
- [[infrastructure-setup]]
- [[dockerfile-consolidation]]
- [[database-schema]]
- [[system-architecture]]
