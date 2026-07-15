# DB Migration Container Design

Source: docs/superpowers/specs/2026-06-17-db-migration-container-design.md
Primary-Topic: database-migration-container-design
Secondary-Topics: docker-compose-service-dependencies

## Key Concepts

- Status: Approved, dated 2026-06-17.
- Problem: `just up-build` starts the `backend` container without first running database migrations. On a fresh environment with no volumes, the `backend` service starts against an empty schema and any DB operation fails because migrations were previously a separate manual step rather than a startup prerequisite.
- Goal: guarantee `alembic upgrade head` completes successfully before the `backend` service starts, using Docker Compose's native dependency ordering (not a manual/external step).
- Approach: add a new `db_migration` service to `docker-compose.yml`. It reuses the existing backend image/build context, overrides the container command to `alembic upgrade head`, and is expected to exit (one-shot job, not a long-running service). The `backend` service declares a dependency on `db_migration` using `condition: service_completed_successfully`.
- Startup order (Docker Compose dependency graph):
  1. `app_postgres` must reach `healthy` status.
  2. `db_migration` then runs and must exit 0 (`service_completed_successfully`).
  3. `backend` then starts uvicorn.
  - `ollama-checker` runs in parallel with `db_migration` (not sequentially dependent on it); `backend` waits for both `db_migration` and `ollama-checker` to complete successfully.
- `db_migration` service definition (docker-compose.yml):
  - `build.context: ./apps/backend`, `build.dockerfile: ../../docker/Dockerfile.backend` — same Dockerfile as `backend`, no new Dockerfile or image is introduced.
  - `command: alembic upgrade head` — overrides whatever the backend image's default command is.
  - `env_file: ./apps/backend/.env`.
  - `networks: [app_network]`.
  - `depends_on: { app_postgres: { condition: service_healthy } }`.
- `alembic.ini` sets `script_location = alembic`; `alembic/env.py` overrides the DB URL from `settings.database_url` (sourced from `.env`) — so no extra configuration is needed inside the `db_migration` container beyond what already exists for `backend`.
- Updated `backend.depends_on` block (docker-compose.yml) becomes:
  - `app_postgres: { condition: service_healthy }`
  - `db_migration: { condition: service_completed_successfully }`
  - `ollama-checker: { condition: service_completed_successfully }`
- Error handling:
  - If `alembic upgrade head` exits non-zero, Docker Compose marks `db_migration` as `service_completed_unsuccessfully`, which blocks `backend` from starting at all — failure is fail-closed, not silently ignored.
  - No restart policy is set on `db_migration` — it is intentionally a one-shot job; automatically retrying a failed migration would just hit the same error again (migrations are not idempotent-safe to blindly retry without investigation).
  - The `just migrate` Justfile target (a host-side command for local dev, run outside Docker) is unchanged by this design — it remains a separate manual path for developers who want to run migrations directly on the host.
- Files changed: only `docker-compose.yml` — add the new `db_migration` service definition, and add the `db_migration: service_completed_successfully` condition to `backend.depends_on`. Explicitly no new Dockerfile and no new image; `db_migration` builds from the same `Dockerfile.backend` used by `backend`.
