# DB Migration Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `db_migration` Docker Compose service that runs `alembic upgrade head` and exits before the `backend` service starts.

**Architecture:** A new `db_migration` service in `docker-compose.yml` builds from the same `Dockerfile.backend` as `backend`, overrides the command to `alembic upgrade head`, and is declared as a `service_completed_successfully` dependency of `backend`. No new Dockerfile or source code is needed.

**Tech Stack:** Docker Compose `depends_on` conditions, Alembic, existing `Dockerfile.backend`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `docker-compose.yml` | Modify | Add `db_migration` service; add it to `backend.depends_on` |

---

### Task 1: Add `db_migration` service to `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Open `docker-compose.yml` and locate the `backend` service block (line ~59)**

The file currently has these services: `ollama-checker`, `app_postgres`, `phoenix_postgres`, `phoenix`, `backend`.

- [ ] **Step 2: Insert the `db_migration` service block before the `backend` service**

Add this block between the `phoenix` service and the `backend` service:

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

- [ ] **Step 3: Update `backend.depends_on` to wait for `db_migration`**

The current `backend.depends_on` block is:

```yaml
    depends_on:
      app_postgres:
        condition: service_healthy
      ollama-checker:
        condition: service_completed_successfully
```

Replace it with:

```yaml
    depends_on:
      app_postgres:
        condition: service_healthy
      db_migration:
        condition: service_completed_successfully
      ollama-checker:
        condition: service_completed_successfully
```

- [ ] **Step 4: Verify the final `docker-compose.yml` structure is correct**

Run:
```bash
docker compose -f docker-compose.yml config --quiet
```

Expected: no output (exit 0). Any YAML syntax error will be reported here.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add db_migration service to run alembic migrations before backend starts"
```

---

### Task 2: Verify runtime behaviour

**Files:** none — observation only

- [ ] **Step 1: Start the stack**

```bash
just up-build
```

- [ ] **Step 2: Confirm `db_migration` runs and exits before `backend` starts**

In the compose log output, you should see lines similar to:

```
db_migration-1  | INFO  [alembic.runtime.migration] Running upgrade -> 001, initial_schema
db_migration-1 exited with code 0
backend-1       | INFO:     Started server process
backend-1       | INFO:     Application startup complete.
```

Key checks:
- `db_migration` log lines appear **before** `backend` startup lines
- `db_migration` exits with code **0**
- `backend` starts successfully (no `relation does not exist` errors in its logs)

- [ ] **Step 3: Confirm the health endpoint responds**

```bash
curl -s http://localhost:3001/health
```

Expected:
```json
{"status": "ok"}
```

- [ ] **Step 4: Tear down**

```bash
just down
```
