# Dockerfile Consolidation Design

Source: docs/superpowers/specs/2026-06-17-dockerfile-consolidation-design.md
Primary-Topic: dockerfile-consolidation
Secondary-Topics: docker-compose, repo-structure

## Key Concepts

- Design doc dated 2026-06-17, status Approved.
- Goal: move `apps/backend/Dockerfile` into the `docker/` folder so all Docker-related files are co-located.
- `docker/` already contains `ollama-checker.sh`; after this change it becomes the canonical home for every Docker artifact.
- Approach is a single move plus reference updates — no content changes to the Dockerfile itself.
- File move: `apps/backend/Dockerfile` → `docker/Dockerfile.backend`.
- Naming convention introduced: Dockerfiles live in `docker/` named `Dockerfile.<service>` (e.g. `Dockerfile.backend`).
- `docker-compose.yml` change: build context stays `./apps/backend` (source files remain there); only the `dockerfile:` path changes to `../../docker/Dockerfile.backend`.
- The `../../` prefix is relative to the build context (`./apps/backend`), resolving back to the workspace root and then into `docker/`.
- `docs/codebase/002-repo-structure.md` updates: remove `Dockerfile` from the `apps/backend/` block; add a `Dockerfile.backend` entry under `docker/`.
- `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md` updates: remove the `Dockerfile, alembic.ini ← unchanged` reference in the directory structure block; update the "What Does NOT Change" Docker bullet to reflect the new path.
- `CLAUDE.md` update: add a key pattern documenting that Dockerfiles live in `docker/` named `Dockerfile.<service>`, with each service's build context remaining its own app directory (`apps/<service>/`).
- Explicitly out of scope / unchanged: Dockerfile contents (zero changes inside the file), build context (`./apps/backend`, so all `COPY` instructions remain valid), `alembic.ini` location, and any application source code.
