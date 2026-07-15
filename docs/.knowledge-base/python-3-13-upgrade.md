# Python 3.13 Upgrade

A routine toolchain-currency bump — Python 3.12 to 3.13 across local development and the Docker runtime, executed as a mechanical version-pin change with no behavior change and one hard gate on dependency wheel availability.

## Key Concepts

- **Framing**: explicitly "a pin bump, not a design decision" — not driven by any dependency requirement or 3.13-only language feature. No architectural decision was made; the approach is bump every version-declaration point, regenerate derived lockfile/venv/image, then verify.
- **Execution strategy**: run sequentially, not via the `autonomous-feature-development` skill's parallel-worktree pipeline — Task 2 and Task 3 explicitly consume artifacts Task 1 produces (the regenerated `.venv`/`uv.lock`, then the Dockerfile change), and Task 3 mutates shared Docker/Ollama port state, so parallel worktree agents would have raced or verified against a stale pre-upgrade environment. Confirmed with the user before proceeding.
- **Hard gate**: if `uv lock` cannot resolve a cp313 wheel for any existing dependency, the upgrade is blocked outright — no pinning an older sub-dependency, no `--no-binary` workaround, no silently skipping the package. The exact offending package and error must be reported and the work stops there. See [[dependency-management]].
- **Dependencies flagged as highest wheel-availability risk on cp313**: `spacy`, `presidio-analyzer`, `presidio-anonymizer`, `psycopg2-binary`, `arize-phoenix-otel`, `langgraph-checkpoint-postgres`. All six resolved cleanly with cp313 wheels, so the hard gate did not trip.
- **Explicitly out of scope**: application source code, `docker-compose.yml`, database schema/migrations, CI config (none exists in this repo), and historical planning docs under `docs/superpowers/plans/` and `docs/superpowers/specs/` — rewriting those would falsify history.

## Files Changed

- `apps/backend/pyproject.toml` and `apps/eval/pyproject.toml`: `requires-python = ">=3.12"` → `">=3.13"` — same open-ended lower-bound style as before, bumped on both workspace members. See [[uv-workspace-restructure]].
- `ruff.toml`: `target-version = "py312"` → `"py313"`.
- `docker/Dockerfile.backend`: `FROM python:3.12-slim` → `FROM python:3.13-slim` — no patch-version pin, matching the prior convention. See [[docker-compose]] and [[dockerfile-consolidation]].
- `docs/codebase/001-tech-stack.md` and `docs/codebase/003-system-architecture.md`: table-row text "Python 3.12" → "Python 3.13".
- New file `.python-version` (repo root), created via `uv python pin 3.13` — not hand-written, so its content matches exactly what `uv` produces. No such file existed before; local dev previously relied solely on the `requires-python` lower bound.
- Regenerated (not hand-edited): `uv.lock` via `uv lock`; `.venv` via `just clean-python && uv sync --all-extras` (after `uv python install 3.13`).

## Verification

- **Task 1 — toolchain regeneration**: `uv python install 3.13` (installs or confirms already installed); `uv python pin 3.13` writes `.python-version`; `uv lock` resolved 168 packages including every at-risk compiled-wheel package listed above; `uv sync --all-extras` installed 164 packages; `uv run python --version` → `Python 3.13.13`.
- **Task 2 — local suite, both workspace members**: `just lint` → `All checks passed!`; `just format && git status --porcelain` → no diff; `just type-check` → 0 errors/0 warnings from basedpyright; `just test-unit` → 209 passed; `just test-eval` → 90 passed (called out separately since `apps/eval`'s `requires-python` was also bumped and shares the regenerated `.venv`/`uv.lock`). See [[type-checking]].
- **Task 3 — Docker runtime, the final acceptance criterion**: `just up-all` → build completes, `db_migration` exits 0, `backend` reaches running state with no import/startup errors; `docker compose exec backend python --version` → `Python 3.13.14`; a real `POST /query` request returns HTTP 200 with a body matching `QueryResponse` (`answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`, `retrievedContexts`) — not a 500 or connection error; `just down-all` → clean exit.
- **Rollback plan** (documented, not exercised — the hard gate never tripped): `git checkout --` the six version-declaration files, delete `.python-version`, then regenerate `uv.lock`/`.venv`/the Docker image against 3.12. Pure code revert — no data or schema impact.
- **Review verdict**: `enhanced-review` gave Good Taste / SHIP IT — diff matches spec exactly, the hard gate was genuinely exercised (not theater), no findings.
- The upgrade itself did not cause the four independent root causes later found by the integration-test investigation — it only surfaced them by forcing a fresh full-stack run. See [[integration-testing]].

## Sources

- Python 3.13 Upgrade Implementation Plan — `docs/superpowers/plans/2026-07-03-python-3-13-upgrade.md`
- Python 3.13 Upgrade Design — `docs/superpowers/specs/2026-07-03-python-3-13-upgrade-design.md`

## Related Topics

- [[dependency-management]]
- [[docker-compose]]
- [[dockerfile-consolidation]]
- [[infrastructure-setup]]
- [[integration-testing]]
- [[type-checking]]
- [[uv-workspace-restructure]]
