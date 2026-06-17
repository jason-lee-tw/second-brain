# Dockerfile Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `apps/backend/Dockerfile` into `docker/Dockerfile.backend` so all Docker-related files are co-located in `docker/`.

**Architecture:** The Dockerfile is renamed and relocated; the build context in `docker-compose.yml` stays `./apps/backend` so all `COPY` instructions remain valid. The `dockerfile` field is updated to a path relative to the build context (`../../docker/Dockerfile.backend`). No file contents change — only the file's location and all references to it.

**Tech Stack:** Docker, Docker Compose, bash (`docker compose config` for validation)

---

## Files Changed

| Action | Path |
|--------|------|
| Move (rename) | `apps/backend/Dockerfile` → `docker/Dockerfile.backend` |
| Modify | `docker-compose.yml` |
| Modify | `docs/codebase/002-repo-structure.md` |
| Modify | `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md` |
| Modify | `CLAUDE.md` |

---

### Task 1: Move the Dockerfile

**Files:**
- Move: `apps/backend/Dockerfile` → `docker/Dockerfile.backend`

- [ ] **Step 1: Move the file**

```bash
mv apps/backend/Dockerfile docker/Dockerfile.backend
```

- [ ] **Step 2: Verify the move**

```bash
ls docker/
# Expected output includes: Dockerfile.backend  ollama-checker.sh
ls apps/backend/Dockerfile 2>/dev/null || echo "Gone — good"
# Expected: Gone — good
```

- [ ] **Step 3: Commit**

```bash
git add docker/Dockerfile.backend apps/backend/Dockerfile
git commit -m "refactor: move Dockerfile to docker/Dockerfile.backend"
```

---

### Task 2: Update docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

The `backend.build` block currently reads:

```yaml
backend:
  build:
    context: ./apps/backend
    dockerfile: Dockerfile
```

The `dockerfile` path is resolved relative to the `context` directory. From `./apps/backend`, `../../docker/Dockerfile.backend` walks back to the workspace root then into `docker/`.

- [ ] **Step 1: Edit docker-compose.yml**

Change the `dockerfile` line in the `backend` service's `build` block:

```yaml
backend:
  build:
    context: ./apps/backend
    dockerfile: ../../docker/Dockerfile.backend
```

All other lines in the `backend` service remain unchanged.

- [ ] **Step 2: Validate the compose file**

```bash
docker compose config --quiet
# Expected: exits 0 with no errors
```

If `docker compose config` prints the resolved config without errors, the path is valid.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "fix: update docker-compose to reference docker/Dockerfile.backend"
```

---

### Task 3: Update docs/codebase/002-repo-structure.md

**Files:**
- Modify: `docs/codebase/002-repo-structure.md`

The current structure doc lists `Dockerfile` under `apps/backend/` and only `ollama-checker.sh` under `docker/`. Two edits:

1. Remove the `Dockerfile` line from the `apps/backend/` block.
2. Add `Dockerfile.backend` to the `docker/` block.

- [ ] **Step 1: Edit the repo structure doc**

In the `apps/backend/` section, remove:
```
  Dockerfile
```

In the `docker/` section, change:
```
docker/
  ollama-checker.sh       ← waits for Ollama to be ready before starting backend
```
to:
```
docker/
  Dockerfile.backend      ← backend service image build file
  ollama-checker.sh       ← waits for Ollama to be ready before starting backend
```

- [ ] **Step 2: Commit**

```bash
git add docs/codebase/002-repo-structure.md
git commit -m "docs: update repo structure — Dockerfile moved to docker/"
```

---

### Task 4: Update workspace-restructure-design.md

**Files:**
- Modify: `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md`

Two locations reference the Dockerfile:

1. **Directory structure block (line ~29):** currently reads `Dockerfile, alembic.ini   ← unchanged`. Remove `Dockerfile,` from that entry.
2. **"What Does NOT Change" section:** currently says "Docker build context (`apps/backend/`) and `Dockerfile`". Update to name the new path.

- [ ] **Step 1: Edit the directory structure block**

Find the line:
```
      Dockerfile, alembic.ini   ← unchanged
```
Change to:
```
      alembic.ini               ← unchanged
```

- [ ] **Step 2: Edit the "What Does NOT Change" section**

Find:
```
- Docker build context (`apps/backend/`) and `Dockerfile`
```
Change to:
```
- Docker build context (`apps/backend/`) — `Dockerfile` relocated to `docker/Dockerfile.backend`
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-17-workspace-restructure-design.md
git commit -m "docs: update workspace-restructure spec — Dockerfile moved to docker/"
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Add a key pattern under the existing `**Key patterns:**` bullet list to record the Docker file convention.

- [ ] **Step 1: Add the key pattern**

In the `**Key patterns:**` list (after the last existing bullet), add:

```markdown
- Dockerfiles live in `docker/` named `Dockerfile.<service>` (e.g. `Dockerfile.backend`) — each service's build context remains its own app directory (`apps/<service>/`).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record Docker file convention in CLAUDE.md"
```
