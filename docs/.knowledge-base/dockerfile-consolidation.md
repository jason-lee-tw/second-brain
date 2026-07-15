# Dockerfile Consolidation

`apps/backend/Dockerfile` was moved to `docker/Dockerfile.backend` so all Docker-related files are co-located under `docker/` instead of scattered per-app, with zero changes to the Dockerfile's contents.

## Key Concepts

- **Goal**: move `apps/backend/Dockerfile` into `docker/Dockerfile.backend` so all Docker artifacts live in one place; `docker/` already held `ollama-checker.sh` and becomes the canonical home for every Docker file.
- **Design date**: 2026-06-17, status Approved.
- **Approach**: a single file move plus reference updates — no content changes to the Dockerfile itself.
- **Build context stays put**: the Docker build context in `docker-compose.yml` remains `./apps/backend` (source files, including anything the Dockerfile `COPY`s, stay where they are) — only the `dockerfile:` path changes, to `../../docker/Dockerfile.backend`. The `../../` prefix is relative to the build context and walks back to the workspace root before descending into `docker/`.
- **Naming convention established**: Dockerfiles live in `docker/` named `Dockerfile.<service>` (e.g. `Dockerfile.backend`); each service's build context remains its own app directory (`apps/<service>/`). This convention was recorded directly in the root `CLAUDE.md` under "Key patterns."
- **Tech involved**: Docker, Docker Compose, bash — validated via `docker compose config --quiet`, expected to exit 0 with no errors.
- **Explicitly out of scope / unchanged**: Dockerfile contents, the build context (`./apps/backend`), `alembic.ini` location, and any application source code.

## Files Changed

- Move (rename): `apps/backend/Dockerfile` → `docker/Dockerfile.backend`.
- Modify: `docker-compose.yml` — backend service's `build.dockerfile` field changes from `Dockerfile` to `../../docker/Dockerfile.backend`; all other backend service lines unchanged.
- Modify: `docs/codebase/002-repo-structure.md` — remove `Dockerfile` from the `apps/backend/` listing; add a `Dockerfile.backend` entry (with a comment identifying it as the backend service image build file) to the `docker/` listing.
- Modify: `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md` — remove the `Dockerfile, alembic.ini ← unchanged` line from the directory structure block; update the "What Does NOT Change" section to state the Dockerfile relocated to `docker/Dockerfile.backend` rather than staying in `apps/backend/`. This reflects that the earlier workspace-restructure design had assumed the Dockerfile stayed under `apps/backend/`, and this consolidation is a follow-up/cleanup to that design.
- Modify: `CLAUDE.md` — append a "Key patterns" bullet recording the Dockerfile-in-`docker/` naming convention.

## Execution

- Recommended execution via `superpowers:subagent-driven-development` or `superpowers:executing-plans`, working through the plan task-by-task with checkbox (`- [ ]`) progress tracking.
- The plan lands as five separate, atomic commits (one per task):
  1. `refactor: move Dockerfile to docker/Dockerfile.backend`
  2. `fix: update docker-compose to reference docker/Dockerfile.backend`
  3. `docs: update repo structure — Dockerfile moved to docker/`
  4. `docs: update workspace-restructure spec — Dockerfile moved to docker/`
  5. `docs: record Docker file convention in CLAUDE.md`
- Verification per task: after the move, confirm `docker/` contains `Dockerfile.backend` and `ollama-checker.sh`, and that `apps/backend/Dockerfile` no longer exists; after the compose edit, `docker compose config --quiet` should exit 0 with no output.

## Sources

- [Dockerfile Consolidation Implementation Plan] — `docs/superpowers/plans/2026-06-17-dockerfile-consolidation.md`
- [Dockerfile Consolidation Design] — `docs/superpowers/specs/2026-06-17-dockerfile-consolidation-design.md`
- [Repo Structure] — `docs/codebase/002-repo-structure.md`

## Related Topics

- [[repo-structure]]
- [[docker-compose]]
- [[database-migration-container]]
- [[infrastructure-setup]]
- [[python-3-13-upgrade]]
- [[uv-workspace-restructure]]
