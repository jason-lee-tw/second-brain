# DB Migration Container Design

**Date:** 2026-06-17
**Status:** Approved

## Problem

`just up-build` starts the backend without running database migrations. On a fresh environment (no volumes), the `backend` container starts against an empty schema and any DB operation fails. Migrations must be run as a prerequisite step, not as a separate manual command.

## Goal

Ensure `alembic upgrade head` completes successfully before the `backend` service starts, using Docker Compose's native dependency ordering.

## Approach

Add a `db_migration` service to `docker-compose.yml` that reuses the backend image, overrides the command to `alembic upgrade head`, and exits. The `backend` service depends on it with `condition: service_completed_successfully`.

## Architecture

Startup order:

```
app_postgres (healthy)
    └─► db_migration  (exits 0)
            └─► backend (starts uvicorn)
```

`ollama-checker` continues to run in parallel with `db_migration`; `backend` waits for both.

## Service Definition

```yaml
db_migration:
  build:
    context: ./apps/backend
    dockerfile: ../../docker/Dockerfile.backend
  command: alembic upgrade head
  env_file:
    - ./apps/backend/.env
  networks:
    - app_network
  depends_on:
    app_postgres:
      condition: service_healthy
```

`alembic.ini` sets `script_location = alembic`; `alembic/env.py` overrides the DB URL from `settings.database_url` (sourced from `.env`). No extra configuration is needed inside the container.

## Updated `backend.depends_on`

```yaml
depends_on:
  app_postgres:
    condition: service_healthy
  db_migration:
    condition: service_completed_successfully
  ollama-checker:
    condition: service_completed_successfully
```

## Error Handling

- If `alembic upgrade head` exits non-zero, `db_migration` is marked `service_completed_unsuccessfully` by Docker Compose, which blocks `backend` from starting.
- No restart policy is set on `db_migration` — it is a one-shot job; retrying a failed migration would hit the same error.
- The `just migrate` Justfile target (host-side, for local dev) is unchanged.

## Files Changed

| File | Change |
|---|---|
| `docker-compose.yml` | Add `db_migration` service; add `db_migration: service_completed_successfully` to `backend.depends_on` |

No new Dockerfile, no new image — `db_migration` builds from the same `Dockerfile.backend` as `backend`.
