# Dockerfile Consolidation Implementation Plan

Source: docs/superpowers/plans/2026-06-17-dockerfile-consolidation.md
Primary-Topic: dockerfile-organization
Secondary-Topics: repo-structure, docker-compose-configuration

## Key Concepts

- Goal: move `apps/backend/Dockerfile` into `docker/Dockerfile.backend` so all Docker-related files are co-located under `docker/` instead of scattered per-app.
- Architecture decision: the Dockerfile is renamed and relocated, but the Docker build context in `docker-compose.yml` stays `./apps/backend` — this keeps all `COPY` instructions inside the Dockerfile valid without rewriting paths.
- The `dockerfile` field in the compose file's `build` block is updated to a path relative to the build context: `../../docker/Dockerfile.backend` (walks from `./apps/backend` back to workspace root, then into `docker/`).
- No file contents change in the Dockerfile itself — only its location and every reference to that location across the repo.
- Naming convention established: Dockerfiles live in `docker/` named `Dockerfile.<service>` (e.g. `Dockerfile.backend`); each service's build context remains its own app directory (`apps/<service>/`). This convention was later recorded directly in the root `CLAUDE.md` under "Key patterns."
- Tech stack involved: Docker, Docker Compose, bash (validation via `docker compose config --quiet`, expected to exit 0 with no errors).
- Files changed by this plan:
  - Move (rename): `apps/backend/Dockerfile` → `docker/Dockerfile.backend`
  - Modify: `docker-compose.yml` (backend service's `build.dockerfile` field)
  - Modify: `docs/codebase/002-repo-structure.md` (remove `Dockerfile` from `apps/backend/` listing, add `Dockerfile.backend` to `docker/` listing with a comment "backend service image build file")
  - Modify: `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md` (two edits: remove `Dockerfile,` from the directory structure block near the `alembic.ini` line; update the "What Does NOT Change" section to say the Dockerfile relocated to `docker/Dockerfile.backend` rather than staying in `apps/backend/`)
  - Modify: `CLAUDE.md` (add the Dockerfile-naming key pattern bullet)
- Execution guidance for agentic workers: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` skill to work through the plan task-by-task; steps use checkbox (`- [ ]`) syntax for progress tracking.
- Task 1 (Move the Dockerfile): run `mv apps/backend/Dockerfile docker/Dockerfile.backend`; verify with `ls docker/` (expect `Dockerfile.backend` and `ollama-checker.sh`) and confirm `apps/backend/Dockerfile` no longer exists; commit with message `refactor: move Dockerfile to docker/Dockerfile.backend`.
- Task 2 (Update docker-compose.yml): change the backend service's `build.dockerfile` value from `Dockerfile` to `../../docker/Dockerfile.backend`, leaving all other backend service lines unchanged; validate via `docker compose config --quiet`; commit with message `fix: update docker-compose to reference docker/Dockerfile.backend`.
- Task 3 (Update repo structure doc `docs/codebase/002-repo-structure.md`): remove the `Dockerfile` line from the `apps/backend/` block; add a `Dockerfile.backend      ← backend service image build file` line to the `docker/` block (alongside the existing `ollama-checker.sh` entry); commit with message `docs: update repo structure — Dockerfile moved to docker/`.
- Task 4 (Update `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md`): in the directory structure block, change the line `Dockerfile, alembic.ini   ← unchanged` to `alembic.ini               ← unchanged`; in the "What Does NOT Change" section, change "Docker build context (`apps/backend/`) and `Dockerfile`" to "Docker build context (`apps/backend/`) — `Dockerfile` relocated to `docker/Dockerfile.backend`"; commit with message `docs: update workspace-restructure spec — Dockerfile moved to docker/`.
- Task 5 (Update root `CLAUDE.md`): append a new bullet to the existing "Key patterns" list recording the Dockerfile-in-`docker/` naming convention (`Dockerfiles live in docker/ named Dockerfile.<service> ... each service's build context remains its own app directory`); commit with message `docs: record Docker file convention in CLAUDE.md`.
- Each task in the plan ends with its own git commit, meaning the consolidation lands as five separate, atomic commits rather than one large change.
- The plan references an earlier related design document (`docs/superpowers/specs/2026-06-17-workspace-restructure-design.md`) describing a broader workspace restructure, of which this Dockerfile move is a follow-up/cleanup step — the restructure doc previously assumed the Dockerfile stayed under `apps/backend/`.
