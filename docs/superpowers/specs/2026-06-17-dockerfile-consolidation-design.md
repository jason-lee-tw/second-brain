# Dockerfile Consolidation Design

**Date:** 2026-06-17
**Status:** Approved

## Goal

Move `apps/backend/Dockerfile` into the `docker/` folder so all Docker-related files are co-located. The `docker/` directory already contains `ollama-checker.sh`; this change makes it the canonical home for every Docker artifact.

## Approach

Single move + reference updates. The Dockerfile moves to `docker/Dockerfile.backend`. The build context in `docker-compose.yml` stays `./apps/backend` (source files live there); only the `dockerfile` path changes. All docs and CLAUDE.md are updated to reflect the new location.

## Changes

### 1. File move

`apps/backend/Dockerfile` → `docker/Dockerfile.backend`

### 2. `docker-compose.yml`

```yaml
backend:
  build:
    context: ./apps/backend
    dockerfile: ../../docker/Dockerfile.backend # was: Dockerfile
```

`../../` is relative to the build context (`./apps/backend`), resolving back to the workspace root then into `docker/`.

### 3. `docs/codebase/002-repo-structure.md`

- Remove `Dockerfile` from the `apps/backend/` block.
- Add `Dockerfile.backend` entry under `docker/`.

### 4. `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md`

- Directory structure block: remove `Dockerfile, alembic.ini  ← unchanged` reference to Dockerfile.
- "What Does NOT Change" section: update Docker bullet to reflect new path.

### 5. `CLAUDE.md`

Add key pattern: Dockerfiles live in `docker/` named `Dockerfile.<service>`; each service's build context remains its own app directory.

## What Does NOT Change

- Dockerfile contents (zero changes inside the file)
- Build context (`./apps/backend`) — all `COPY` instructions remain valid
- `alembic.ini` location
- Any application source code
