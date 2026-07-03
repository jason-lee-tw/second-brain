# Python 3.13 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Progress — 2026-07-03

**Status: Done, verified, reviewed. Commit `32945f5` on branch `config/000-upgrade-python-3-13`, ahead of `origin` (push pending — attempted push was denied by permission prompt, needs a manual push).**

- Executed sequentially, not via the autonomous-feature-development skill's parallel-worktree pipeline: Tasks 2 and 3 explicitly consume artifacts Task 1 produces (the regenerated `.venv`/`uv.lock`, then the Dockerfile change), and Task 3 mutates shared Docker/Ollama port state — parallel worktree agents would have raced or verified against a stale pre-upgrade environment. Confirmed with user before proceeding.
- Task 1: all 6 files edited, `.python-version` created via `uv python pin`, `uv.lock` regenerated. Hard gate cleared — `uv lock` resolved 168 packages including all flagged at-risk compiled-wheel packages (spacy, presidio-analyzer/anonymizer, psycopg2-binary, arize-phoenix-otel, langgraph-checkpoint-postgres). `uv sync --all-extras` installed 164 packages; `uv run python --version` → `Python 3.13.13`. Committed as `32945f5`.
- Task 2: `just lint` clean, `just format` made no changes, `just type-check` → 0 errors/0 warnings, `just test-unit` → 209 passed, `just test-eval` → 90 passed. No code changes needed, nothing to commit.
- Task 3: `just up-all` built and started the stack on `python:3.13-slim`; `docker compose exec backend python --version` → `Python 3.13.14`; `POST /query` → HTTP 200 with full expected schema; `just down-all` tore down cleanly.
- `enhanced-review` verdict: 🟢 Good Taste / ✅ SHIP IT — diff matches spec exactly, hard gate was exercised (not theater), no findings.
- Remaining: push `32945f5` to `origin/config/000-upgrade-python-3-13` to update PR #16 (open, no CI configured, no review threads).

**Goal:** Move the project's Python version from 3.12 to 3.13 across local development and the Docker runtime, with no behavior change.

**Architecture:** Not applicable — this is a version-pin bump, not a design change. Every declaration point that names "3.12" is updated to "3.13", the lockfile and venv are regenerated against the new interpreter, and the Docker base image is rebuilt.

**Tech Stack:** `uv` (workspace + lockfile + interpreter management), `ruff`, `basedpyright`, `pytest`, Docker Compose.

## Global Constraints

- `requires-python` bound in both workspace members becomes exactly `">=3.13"` (same open-ended lower-bound style as today's `">=3.12"`).
- `ruff.toml` `target-version` becomes exactly `"py313"`.
- Docker base image becomes exactly `python:3.13-slim` — no patch-version pin, matching the existing `python:3.12-slim` convention.
- New `.python-version` file at repo root, created via `uv python pin 3.13` (not hand-written), so its content matches what `uv` itself produces.
- **Hard gate:** if `uv lock` cannot resolve a cp313 wheel for any existing dependency, STOP. Report the exact package and error. Do not pin an older sub-dependency, do not pass `--no-binary`, do not skip the package — the upgrade is blocked until real cp313 support exists.
- Do not touch `docs/superpowers/plans/*` or `docs/superpowers/specs/*` — dated historical records, out of scope.
- No CI config exists in this repo — nothing to update there.
- Spec: `docs/superpowers/specs/2026-07-03-python-3-13-upgrade-design.md`

---

### Task 1: Bump version pins and regenerate the toolchain

**Files:**

- Modify: `apps/backend/pyproject.toml:8`
- Modify: `apps/eval/pyproject.toml:4`
- Modify: `ruff.toml:2`
- Modify: `docker/Dockerfile.backend:1`
- Modify: `docs/codebase/001-tech-stack.md:5`
- Modify: `docs/codebase/003-system-architecture.md:13`
- Create: `.python-version` (via `uv python pin`, not hand-written)
- Regenerate: `uv.lock` (via `uv lock`)
- Regenerate: `.venv` (via `just clean-python` + `uv sync --all-extras`)

**Interfaces:**

- Consumes: nothing (first task).
- Produces: a 3.13-pinned workspace (`uv.lock` with `requires-python = ">=3.13"`, `.venv` running CPython 3.13.x) that Tasks 2 and 3 verify against.

- [x] **Step 1: Edit `apps/backend/pyproject.toml`**

Change line 8 from:

```toml
requires-python = ">=3.12"
```

to:

```toml
requires-python = ">=3.13"
```

- [x] **Step 2: Edit `apps/eval/pyproject.toml`**

Change line 4 from:

```toml
requires-python = ">=3.12"
```

to:

```toml
requires-python = ">=3.13"
```

- [x] **Step 3: Edit `ruff.toml`**

Change line 2 from:

```toml
target-version = "py312"
```

to:

```toml
target-version = "py313"
```

- [x] **Step 4: Edit `docker/Dockerfile.backend`**

Change line 1 from:

```dockerfile
FROM python:3.12-slim
```

to:

```dockerfile
FROM python:3.13-slim
```

- [x] **Step 5: Edit `docs/codebase/001-tech-stack.md`**

On line 5, replace `Python 3.12` with `Python 3.13` in the table row (only the version text changes, table padding is not load-bearing in Markdown).

- [x] **Step 6: Edit `docs/codebase/003-system-architecture.md`**

On line 13, replace `Python 3.12` with `Python 3.13` in the table row.

- [x] **Step 7: Ensure a 3.13 interpreter is available to uv**

Run: `uv python install 3.13`
Expected: either `Installed Python 3.13.x` (fresh download) or confirmation it's already installed. Exit code 0.

- [x] **Step 8: Pin the local interpreter**

Run: `uv python pin 3.13`
Expected: output confirming `.python-version` was written, and a new file `.python-version` at the repo root containing `3.13`.

- [x] **Step 9: Regenerate the lockfile — HARD GATE**

Run: `uv lock`
Expected: `Resolved N packages` with exit code 0.

If this fails with a resolution error naming a specific package (most likely `spacy`, `presidio-analyzer`, `presidio-anonymizer`, `psycopg2-binary`, `arize-phoenix-otel`, or `langgraph-checkpoint-postgres`) because no cp313 wheel exists: **STOP**. Do not modify the dependency's version bound to work around it. Revert Steps 1–8 (`git checkout -- apps/backend/pyproject.toml apps/eval/pyproject.toml ruff.toml docker/Dockerfile.backend docs/codebase/001-tech-stack.md docs/codebase/003-system-architecture.md`, `rm .python-version`, `uv lock`) and report the blocking package to the user.

- [x] **Step 10: Rebuild the local venv on 3.13**

Run: `just clean-python && uv sync --all-extras`
Expected: `.venv` is deleted and recreated; sync ends with `Installed N packages` and exit code 0.

- [x] **Step 11: Verify the venv interpreter version**

Run: `uv run python --version`
Expected: `Python 3.13.x`

- [x] **Step 12: Commit**

```bash
git add apps/backend/pyproject.toml apps/eval/pyproject.toml ruff.toml docker/Dockerfile.backend docs/codebase/001-tech-stack.md docs/codebase/003-system-architecture.md .python-version uv.lock
git commit -m "config: upgrade Python 3.12 to 3.13"
```

---

### Task 2: Local verification suite

**Files:** none (verification only — no files change if Task 1 was done correctly).

**Interfaces:**

- Consumes: the 3.13 `.venv` and `uv.lock` produced by Task 1.
- Produces: confirmation that lint, format, type-check, and unit tests — for both `apps/backend` and `apps/eval` — are green under 3.13, a precondition for Task 3.

- [x] **Step 1: Run lint**

Run: `just lint`
Expected: `All checks passed!` and exit code 0.

- [x] **Step 2: Run format and confirm no diff**

Run: `just format && git status --porcelain`
Expected: `git status --porcelain` prints nothing (ruff format made no changes — the codebase was already 3.13-formatted-compatible).

- [x] **Step 3: Run type check**

Run: `just type-check`
Expected: output ends with `✅ Type check is completed` and no error/warning lines from basedpyright.

- [x] **Step 4: Run backend unit tests**

Run: `just test-unit`
Expected: pytest summary line showing all tests passed, e.g. `N passed in Xs`, exit code 0.

- [x] **Step 5: Run eval unit tests**

Run: `just test-eval`
Expected: pytest summary line showing all tests passed, exit code 0. `apps/eval`'s `requires-python` was also bumped in Task 1 and it shares the same regenerated `.venv`/`uv.lock` as backend, so it needs the same confirmation — `just test-unit` alone does not cover it.

- [ ] **Step 6: If any of Steps 1–5 fail** — not triggered, Steps 1–5 all passed

Do not proceed to Task 3. Diagnose using `superpowers:systematic-debugging` — a failure here means either a 3.13 behavior change surfaced (e.g. a stdlib deprecation now an error) or a resolved dependency version changed behavior. Fix the root cause in application code, re-run the failing command, then continue. Commit the fix as a new commit — do not amend Task 1's commit (per this project's CLAUDE.md: always create new commits rather than amending). Do not weaken lint/type-check rules to paper over the failure.

---

### Task 3: Docker runtime verification

**Files:** none (verification only).

**Interfaces:**

- Consumes: `docker/Dockerfile.backend` from Task 1, a green local suite from Task 2.
- Produces: confirmation the containerized backend runs on 3.13 and serves real requests — the final acceptance criterion from the spec.

**Prerequisite:** `apps/backend/.env` must exist and be populated (same requirement as any normal `just up-all` run) and Ollama must be reachable, per the existing `ollama-checker` service.

- [x] **Step 1: Build the backend image on the new base**

Run: `just up-all`
Expected: `docker compose ... up --build` completes, `db_migration` exits 0, `backend` container reaches a running state, logs show uvicorn started on port 8000 with no import/startup errors.

- [x] **Step 2: Verify the container's Python version**

Run: `docker compose exec backend python --version`
Expected: `Python 3.13.x`

- [x] **Step 3: Exercise the real query path**

Run:

```bash
curl -s -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What is in my second brain?"}'
```

Expected: HTTP 200 with a JSON body containing `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`, `retrievedContexts` fields (per `QueryResponse` in `apps/backend/src/second_brain/api/schemas.py`) — not a 500 or a connection error.

- [x] **Step 4: Tear down**

Run: `just down-all`
Expected: containers stop cleanly, exit code 0.

- [ ] **Step 5: If Steps 1–3 fail** — not triggered, Steps 1–3 all passed

Do not report the upgrade as done. Capture the exact error (build log, container log, or HTTP response) and diagnose via `superpowers:systematic-debugging` before retrying.
