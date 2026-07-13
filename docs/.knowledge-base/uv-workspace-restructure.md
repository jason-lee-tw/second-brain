# UV Workspace Restructure

Converts the project from a single backend-only `pyproject.toml` into a `uv` workspace with a thin root container, a single shared lockfile/venv, and two members — `apps/backend` and `apps/eval`.

## Key Concepts

- **Goal**: move from a single backend-only `pyproject.toml` to a `uv` workspace so `apps/eval` becomes a proper workspace member instead of a loose scripts folder under a top-level `eval/` directory.
- **Approach chosen**: "uv workspace, thin root" — root `pyproject.toml` contains only `[tool.uv.workspace]` (`members = ["apps/backend", "apps/eval"]`) and has no `[project]` section, so the workspace root itself is not an installable package.
- **Single shared lockfile/venv**: one `uv.lock` and one `.venv/` live at the project root, shared by every workspace member — no per-member lockfiles or venvs. Migration mechanics: `git rm apps/backend/uv.lock` (was git-tracked), `rm -rf apps/backend/.venv` (was gitignored), then `uv sync --all-extras` from the project root creates the root-level `uv.lock` and `.venv/`.
- **`apps/eval` becomes a real workspace member**: `git mv eval/dataset apps/eval/dataset`, then `rmdir eval` once the old top-level `eval/` directory is empty. `apps/eval/pyproject.toml` is new — package name `second-brain-eval`, build-system `hatchling`, `requires-python = ">=3.12"`, depends on `ragas>=0.2.0` and on `second-brain` (resolved automatically by `uv` as an intra-workspace cross-reference to `apps/backend/`, no path hacks). Sets `[tool.uv] package = false` — marks it a virtual member with no installable wheel, since eval is scripts-only (`generate_dataset.py`, `baseline.py`, `run_eval.py`, `compare.py`, `dataset/`).
- **`apps/backend/pyproject.toml` changes**: drops `[tool.pytest.ini_options]` (superseded by `pytest.ini`), drops the `eval` optional-dependency group (moved to `apps/eval/pyproject.toml`), adds `ruff>=0.9.0` to the `dev` optional-dependencies group. Package name stays `second-brain`, still built via hatchling from `src/second_brain`; all runtime/dev dependencies otherwise unchanged.
- **Verification**: `just lint` passes, `uv run ruff format --check .` reports files already formatted, `just test-unit` passes, and both `import second_brain` and `import ragas` succeed from the workspace venv. Importing `second_brain.config.settings` directly is intentionally avoided in this smoke test because pydantic-settings validates env vars at import time and needs a populated `.env`. If lint errors surface during verification, they are fixed and committed separately (`fix: resolve lint errors surfaced by ruff`) rather than folded into the restructure commits.
- **Explicitly NOT changing**: `alembic.ini` location and all alembic commands (still run from `apps/backend/`); `.env` file location (`apps/backend/.env`); all application source code; `docker-compose.yml`; `scripts/init.sh` (uv sync already ran from root); the Docker build context (`apps/backend/`) — though the Dockerfile itself relocates to `docker/Dockerfile.backend` as a separate, related change (see [[dockerfile-consolidation]]).
- **Commit strategy**: each of the 7 plan tasks ends in its own Conventional Commit, e.g. `chore: add root uv workspace pyproject.toml`, `chore: extract ruff/pytest configs to dedicated files, add ruff to dev deps`, `chore: create apps/eval workspace member, move eval/dataset`, `chore: migrate uv lockfile and venv to workspace root`, `chore: update Justfile with workspace-aware lint/format/test/migrate targets`, `docs: update repo structure and build docs for workspace layout`.
- **Documentation fallout**: `docs/codebase/002-repo-structure.md` gets a full rewrite of the repo tree diagram (root `pyproject.toml`/`uv.lock`/`ruff.toml`, `apps/backend/` with `pytest.ini` and no per-app lockfile, `apps/eval/` with its own `pyproject.toml`/`dataset/`/eval scripts); `CLAUDE.md`'s `## Build & Verify` section is updated to reflect `just init` running `uv sync --all-extras` and workspace-scoped `just lint`/`just test-unit`.

## Python Tooling Configuration

- Tool configs move out of inline `[tool.*]` sections in `pyproject.toml` into dedicated files: `ruff.toml` at the repo root holds shared lint/format config for the whole workspace (`line-length = 88`, `target-version = "py312"`, `[lint] select = ["E", "F", "I"]`, `[format] quote-style = "double"`).
- Pytest config moves from `pyproject.toml`'s `[tool.pytest.ini_options]` into a per-member `apps/backend/pytest.ini`: `[pytest]` section with `testpaths = tests`, `asyncio_mode = auto`, `pythonpath = src`.

## Justfile Recipes

The Justfile is rewritten to be workspace-aware:

- `lint` / `format` run `uv run ruff check .` / `uv run ruff format .` across the whole workspace (not scoped to a single member).
- `test-unit` / `test-integration` / `test` all use `uv run --package second-brain pytest apps/backend/tests/...` to scope the pytest invocation to the backend package.
- `migrate` still `cd`s into `apps/backend` for Alembic.
- Also includes `init`, `up-ollama`/`down-ollama`, `up-build`/`down`, `up-all`/`down-all`, `down-clean` (docker volume prune + temp folder cleanup), and `clean-python` (removes all `.venv` dirs, `__pycache__`, `.pytest_cache`, `*.pyc`, `.ruff_cache`) targets.
- Developer workflow before/after: installing deps goes from `cd apps/backend && uv sync` to `uv sync` from root; running backend tests goes from `cd apps/backend && pytest` to `just test-unit`; lint/format goes from not wired up to `just lint` / `just format`; Alembic migrations go from `cd apps/backend && alembic ...` to `just migrate`; running eval scripts goes from `cd eval && python run_eval.py` to `cd apps/eval && uv run python run_eval.py`; Docker stays `just up-build` before and after.

## Sources

- Workspace Restructure Implementation Plan — `docs/superpowers/plans/2026-06-17-workspace-restructure.md`
- Workspace Restructure Design — `docs/superpowers/specs/2026-06-17-workspace-restructure-design.md`

## Related Topics

- [[repo-structure]]
- [[dependency-management]]
- [[evaluation-harness]]
- [[dockerfile-consolidation]]
- [[python-3-13-upgrade]]
