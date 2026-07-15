# Workspace Restructure Implementation Plan

Source: docs/superpowers/plans/2026-06-17-workspace-restructure.md
Primary-Topic: uv-workspace
Secondary-Topics: justfile, repo-structure

## Key Concepts

- **Goal**: convert the project to a uv workspace with a thin root container, a shared root `.venv`, and two workspace members: `apps/backend` and `apps/eval`.
- **Architecture**: root `pyproject.toml` declares `[tool.uv.workspace]` with `members = ["apps/backend", "apps/eval"]` and has no `[project]` section (workspace root is not itself an installable package).
- A single `uv.lock` and a single `.venv` live at the project root, shared by all workspace members — no per-member lockfiles/venvs.
- Tool configs move to dedicated files instead of living inline in `pyproject.toml`: `ruff.toml` at the repo root (shared lint/format config for the whole workspace), and a per-member `apps/backend/pytest.ini` (testpaths, `asyncio_mode = auto`, `pythonpath = src`).
- The old `eval/` top-level directory is removed; its contents move to `apps/eval/`, which becomes a proper uv workspace member (not just a loose scripts folder).
- `apps/backend/pyproject.toml` changes: drop `[tool.pytest.ini_options]` (superseded by `pytest.ini`), drop the `eval` optional-dependency group, add `ruff>=0.9.0` to the `dev` optional-dependencies group. Package name stays `second-brain`, built via hatchling from `src/second_brain`.
- `apps/eval/pyproject.toml` is new: package name `second-brain-eval`, depends on `ragas>=0.2.0` and `second-brain` (the latter resolved automatically by uv as an intra-workspace cross-reference to `apps/backend/`). Sets `[tool.uv] package = false` — marks it a virtual member with no installable wheel, since eval is scripts-only.
- Migration mechanics for `eval/dataset/`: `git mv eval/dataset apps/eval/dataset`, then `rmdir eval` once empty.
- Lockfile/venv migration: `git rm apps/backend/uv.lock` (was git-tracked), `rm -rf apps/backend/.venv` (was gitignored), then run `uv sync --all-extras` from the project root to create the root-level `uv.lock` and `.venv/`.
- `scripts/init.sh` must call `uv sync --all-extras` (not bare `uv sync`) because `ruff`/`pytest` live in the optional `dev` dependency group and would otherwise be skipped.
- Justfile is rewritten to be workspace-aware: `lint`/`format` run `uv run ruff check .` / `uv run ruff format .` across the whole workspace; `test-unit`/`test-integration`/`test` all use `uv run --package second-brain pytest apps/backend/tests/...` to scope pytest invocation to the backend package; `migrate` still `cd`s into `apps/backend` for Alembic. Also includes `init`, `up-ollama`/`down-ollama`, `up-build`/`down`, `up-all`/`down-all`, `down-clean` (docker volume prune + temp folder cleanup), and `clean-python` (removes all `.venv` dirs, `__pycache__`, `.pytest_cache`, `*.pyc`, `.ruff_cache`) targets.
- Verification task (no file changes) checks: `just lint` passes, `uv run ruff format --check .` reports files already formatted, `just test-unit` passes, and both `import second_brain` and `import ragas` succeed from the workspace venv. Note: importing `second_brain.config.settings` directly is intentionally avoided in this smoke test because pydantic-settings validates env vars at import time and needs a populated `.env`.
- If lint errors surface during verification, fix them and commit separately with `fix: resolve lint errors surfaced by ruff` rather than folding into the restructure commits.
- Documentation updates required after restructure: `docs/codebase/002-repo-structure.md` gets a full rewrite of the repo tree diagram to show the new `pyproject.toml`/`uv.lock`/`ruff.toml` at root, `apps/backend/` (with `pytest.ini`, no per-app lockfile) and `apps/eval/` (with its own `pyproject.toml`, `dataset/`, and eval scripts: `generate_dataset.py`, `baseline.py`, `run_eval.py`, `compare.py`); `CLAUDE.md`'s `## Build & Verify` section is updated to reflect `just init` running `uv sync --all-extras` and workspace-scoped `just lint`/`just test-unit`.
- Each task in the plan (7 total) ends with its own git commit, using Conventional Commit messages, e.g. `chore: add root uv workspace pyproject.toml`, `chore: extract ruff/pytest configs to dedicated files, add ruff to dev deps`, `chore: create apps/eval workspace member, move eval/dataset`, `chore: migrate uv lockfile and venv to workspace root`, `chore: update Justfile with workspace-aware lint/format/test/migrate targets`, `docs: update repo structure and build docs for workspace layout`.
- Plan is written for agentic workers and recommends using the `superpowers:subagent-driven-development` or `superpowers:executing-plans` skill to execute it task-by-task, with checkbox (`- [ ]`) tracking per step.
