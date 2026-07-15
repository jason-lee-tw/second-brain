# Docker Compose

`docker-compose.yml` orchestrates the project's services, isolates them into two networks by security boundary, and sequences startup so migrations and health dependencies run before the backend serves traffic.

## Key Concepts

- **Services** (as of the latest evolution covered by these sources): `ollama-checker`, `app_postgres`, `phoenix_postgres`, `phoenix`, `db_migration`, `backend`.
  - `ollama-checker`: image `curlimages/curl:latest`, `network_mode: host`, runs `docker/ollama-checker.sh`, uses `extra_hosts: ["host.docker.internal:host-gateway"]`, loads `apps/backend/.env`.
  - `app_postgres`: image `pgvector/pgvector:pg16` (later `pg17` per the OTEL/Phoenix plan) — ships the pgvector shared lib pre-installed; the `vector` extension still must be enabled per-database via `CREATE EXTENSION IF NOT EXISTS vector` (done in an Alembic migration, not in Compose). User/password/db = `second_brain`/`secret`/`second_brain`. Port 5432 exposed. Volume `app_postgres_data`. Network `app_network`. Healthcheck `pg_isready -U second_brain`.
  - `phoenix_postgres`: image `postgres:16` (later `postgres:17`), user/password/db = `phoenix`/`phoenix_secret`/`phoenix`. Volume `phoenix_postgres_data`. Network `phoenix_network`. Healthcheck `pg_isready -U phoenix`.
  - `phoenix`: image `arizephoenix/phoenix:latest`, env `PHOENIX_SQL_DATABASE_URL=postgresql://phoenix:phoenix_secret@phoenix_postgres:5432/phoenix`, port 6006 published, network `phoenix_network`, `depends_on: phoenix_postgres` (healthy).
  - `db_migration`: builds from the same `Dockerfile.backend` image as `backend` — no separate Dockerfile or application source code. Overrides only the container `command` to `alembic upgrade head`; `env_file: ./apps/backend/.env`; `networks: [app_network]`; `depends_on: { app_postgres: { condition: service_healthy } }`. It is a one-shot job (no restart policy) inserted between `phoenix` and `backend` in the file.
  - `backend`: build context `./apps/backend`, dockerfile path `../../docker/Dockerfile.backend` (relative to the build context, resolving to the workspace-root `docker/` folder — see [[dockerfile-consolidation]]), `env_file: ./apps/backend/.env`, port 8000 (dev) / 3001 published, network `app_network`, volume `./temp:/app/temp`, `extra_hosts: ["host.docker.internal:host-gateway"]`.
- **Networking / isolation boundary**: `app_network` (backend + `app_postgres` + `db_migration`) and `phoenix_network` (`phoenix` + `phoenix_postgres`) are kept as two separate bridge networks deliberately — the backend container never joins `phoenix_network` directly. It reaches Phoenix only via the host's published port 6006/4317, using `host.docker.internal`. `extra_hosts: ["host.docker.internal:host-gateway"]` is required on `backend` (and `ollama-checker`) because Docker Desktop (Mac/Windows) auto-resolves `host.docker.internal` but Linux Docker hosts do not — the mapping makes it resolve on Linux without affecting Mac/Windows.
- **Named volumes**: `app_postgres_data`, `phoenix_postgres_data`.
- **Service startup ordering / `depends_on` conditions** — this is the core orchestration mechanism used across the project instead of manual sequencing scripts:
  - `phoenix` waits on `phoenix_postgres` (`condition` implied healthy).
  - `db_migration` waits on `app_postgres` (`condition: service_healthy`) before running `alembic upgrade head`.
  - `backend.depends_on` requires: `app_postgres` (`service_healthy`), `db_migration` (`service_completed_successfully`), and `ollama-checker` (`service_completed_successfully`). `ollama-checker` runs in parallel with `db_migration` — they are not sequentially dependent on each other, only both gate `backend`.
  - This makes migration failure fail-closed: if `alembic upgrade head` exits non-zero, Compose marks `db_migration` as `service_completed_unsuccessfully`, and `backend` never starts. See [[database-migration-container]].
- **Compose file organization**: a single `docker-compose.yml` at the workspace root defines all services; Dockerfiles live under `docker/Dockerfile.<service>` (e.g. `docker/Dockerfile.backend`) while each service's build *context* stays its own app directory (e.g. `./apps/backend`) — introduced by the Dockerfile consolidation move (`apps/backend/Dockerfile` → `docker/Dockerfile.backend`) so all Docker artifacts are co-located under `docker/`. See [[dockerfile-consolidation]].
- **Verification pattern used throughout**: `docker compose -f docker-compose.yml config --quiet` for static YAML/syntax validation (no output, exit 0); `docker compose up -d` / `just up-all` / `just up-build` plus `docker compose ps` to confirm expected health/exit states; `curl` against `/health` (and later `/query`) to confirm the backend actually serves traffic after the dependency chain resolves; `docker compose exec app_postgres psql ...` to inspect schema/extension state directly.
- **Python 3.13 upgrade touched Compose indirectly, not directly**: the base image line in `docker/Dockerfile.backend` changed from `FROM python:3.12-slim` to `FROM python:3.13-slim`; `docker-compose.yml` itself required no changes. Runtime verification after the upgrade used the same `just up-all` → `db_migration` exits 0 → `backend` running → `docker compose exec backend python --version` → real `/query` request pattern already established by the migration-container and OTEL/Phoenix work.

## Sources

- [Second Brain — Ticket 1: Infrastructure & Foundation Implementation Plan] — `docs/superpowers/plans/2026-06-16-ticket-1-infrastructure.md`
- [OpenTelemetry + Arize Phoenix Tracing Implementation Plan] — `docs/superpowers/plans/2026-06-16-ticket-2-otel-phoenix.md`
- [DB Migration Container Implementation Plan] — `docs/superpowers/plans/2026-06-17-db-migration-container.md`
- [Python 3.13 Upgrade Implementation Plan] — `docs/superpowers/plans/2026-07-03-python-3-13-upgrade.md`
- [DB Migration Container Design] — `docs/superpowers/specs/2026-06-17-db-migration-container-design.md`
- [Dockerfile Consolidation Design] — `docs/superpowers/specs/2026-06-17-dockerfile-consolidation-design.md`

## Related Topics

- [[infrastructure-setup]]
- [[database-migration-container]]
- [[dockerfile-consolidation]]
- [[otel-phoenix-tracing]]
- [[python-3-13-upgrade]]
- [[repo-structure]]
- [[capstone-requirements]]
- [[second-brain-architecture]]
- [[system-architecture]]
- [[tech-stack]]
