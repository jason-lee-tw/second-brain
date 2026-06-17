# Workspace Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the project to a uv workspace with a thin root container, shared root `.venv`, and two workspace members (`apps/backend`, `apps/eval`).

**Architecture:** Root `pyproject.toml` declares the uv workspace with no `[project]` section. A single `uv.lock` and `.venv` live at the project root. Tool configs use dedicated files (`ruff.toml` at root, per-member `pytest.ini`). The `eval/` directory moves to `apps/eval/` as a proper workspace member.

**Tech Stack:** uv workspace, hatchling, ruff, pytest, pytest-asyncio

---

### Task 1: Create root workspace pyproject.toml

**Files:**
- Create: `pyproject.toml` (project root)

- [ ] **Step 1: Create root pyproject.toml**

Create `/path/to/project/pyproject.toml` with the following content:

```toml
[tool.uv.workspace]
members = ["apps/backend", "apps/eval"]
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add root uv workspace pyproject.toml"
```

---

### Task 2: Create ruff.toml and update backend pyproject + pytest config

**Files:**
- Create: `ruff.toml` (project root)
- Create: `apps/backend/pytest.ini`
- Modify: `apps/backend/pyproject.toml`

- [ ] **Step 1: Create root ruff.toml**

```toml
line-length = 88
target-version = "py312"

[lint]
select = ["E", "F", "I"]

[format]
quote-style = "double"
indent-style = "space"
```

- [ ] **Step 2: Create apps/backend/pytest.ini**

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
pythonpath = src
```

- [ ] **Step 3: Update apps/backend/pyproject.toml**

Replace the full file content. Key changes:
- Remove `[tool.pytest.ini_options]` section (replaced by `pytest.ini`)
- Remove `eval` group from `[project.optional-dependencies]`
- Add `ruff>=0.9.0` to the `dev` optional-dependencies group

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "second-brain"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlmodel>=0.0.22",
    "alembic>=1.14.0",
    "psycopg2-binary>=2.9.10",
    "pgvector>=0.3.6",
    "pydantic-settings>=2.7.0",
    "langchain-anthropic>=0.3.0",
    "langgraph>=0.2.0",
    "anthropic>=0.40.0",
    "tavily-python>=0.5.0",
    "opentelemetry-sdk>=1.28.0",
    "opentelemetry-exporter-otlp-proto-http>=1.28.0",
    "opentelemetry-instrumentation-fastapi>=0.49b0",
    "arize-phoenix-otel>=0.7.0",
    "presidio-analyzer>=2.2.0",
    "presidio-anonymizer>=2.2.0",
    "spacy>=3.8.0",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.9.0",
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.28.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/second_brain"]
```

- [ ] **Step 4: Commit**

```bash
git add ruff.toml apps/backend/pytest.ini apps/backend/pyproject.toml
git commit -m "chore: extract ruff/pytest configs to dedicated files, add ruff to dev deps"
```

---

### Task 3: Create apps/eval workspace member

**Files:**
- Create: `apps/eval/pyproject.toml`
- Move: `eval/dataset/.gitkeep` → `apps/eval/dataset/.gitkeep`

- [ ] **Step 1: Create apps/eval/pyproject.toml**

```toml
[project]
name = "second-brain-eval"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "ragas>=0.2.0",
    "second-brain",
]

[tool.uv]
package = false
```

`"second-brain"` is resolved as a workspace cross-reference — uv maps it to `apps/backend/` automatically.

`package = false` marks this as a virtual member (no installable wheel needed — eval is scripts only).

- [ ] **Step 2: Move eval/dataset/ into apps/eval/**

```bash
mkdir -p apps/eval
git mv eval/dataset apps/eval/dataset
```

- [ ] **Step 3: Remove the now-empty eval/ directory**

```bash
rmdir eval
```

- [ ] **Step 4: Commit**

```bash
git add apps/eval/
git commit -m "chore: create apps/eval workspace member, move eval/dataset"
```

---

### Task 4: Migrate lockfile and venv to project root

**Files:**
- Delete: `apps/backend/uv.lock` (git-tracked — must `git rm`)
- Delete: `apps/backend/.venv` (gitignored — plain `rm -rf`)
- Auto-created: `uv.lock` (root, by `uv sync`)
- Auto-created: `.venv/` (root, by `uv sync`)

- [ ] **Step 1: Remove the backend-scoped lockfile from git**

```bash
git rm apps/backend/uv.lock
```

- [ ] **Step 2: Delete the backend-scoped virtualenv**

```bash
rm -rf apps/backend/.venv
```

- [ ] **Step 3: Update scripts/init.sh to install all extras**

`uv sync` alone only installs non-optional dependencies. Because `ruff` and `pytest` live in the `dev` optional group, the init script must pass `--all-extras`.

Replace `apps/backend/uv.lock` → deleted; replace `uv sync` line in `scripts/init.sh`:

```bash
echo "🔄 Initializing git hooks..."

git config core.hooksPath ./.hooks

chmod +x ./.hooks/commit-msg
chmod +x ./.hooks/pre-commit

echo "✅ Complete initializing git hooks"

echo "🔄 Initializing UV packages..."

uv sync --all-extras

echo "✅ Complete initializing UV packages"
```

- [ ] **Step 4: Run uv sync from project root**

```bash
uv sync --all-extras
```

Expected output: uv resolves all workspace members, creates `uv.lock` at project root, creates `.venv/` at project root.

Verify:
```bash
ls uv.lock .venv/
# Expected: uv.lock  .venv/
```

- [ ] **Step 5: Commit**

```bash
git add uv.lock scripts/init.sh
git commit -m "chore: migrate uv lockfile and venv to workspace root"
```

---

### Task 5: Update Justfile

**Files:**
- Modify: `Justfile`

- [ ] **Step 1: Replace Justfile content**

```just
help:
  @just -l

[group: "Initialize repository"]
init:
  @chmod +x ./scripts/init.sh && \
    ./scripts/init.sh

# Start Ollama
[group: "Ollama"]
up-ollama:
  @chmod +x ./scripts/start-ollama.sh
  @bash ./scripts/start-ollama.sh

# Stop Ollama
[group: "Ollama"]
down-ollama:
  @chmod +x ./scripts/stop-ollama.sh
  @bash ./scripts/stop-ollama.sh

# Run all apps with Docker
[group: "App"]
up-build:
  @docker compose --env-file ./apps/backend/.env -f ./docker-compose.yml up --build

# Stop all apps
[group: "App"]
down:
  @docker compose -f ./docker-compose.yml down

# Start all services including Ollama
[group: "App"]
up-all:
  @just up-ollama up-build

# Stop all services including Ollama
[group: "App"]
down-all:
  @just down-ollama down

# Stop App docker containers and remove volumes
[group: "Clean up"]
down-clean:
  @docker compose -f ./docker-compose.yml down && \
    echo "🔄 Deleting all unused volumes..." && \
    docker volume prune -af && \
    echo "✅ Deleted all unused volumes"
  @echo "🔄 Deleting all temp folders" && \
    find . -type d -name "temp" | xargs rm -rf && \
    echo "✅ Deleted all temp folders"

[group: "Clean up"]
clean-python:
  @rm -rf **/.venv ./.venv
  @echo "'.venv' folders are deleted."
  @find . -not -path './.git/*' -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null; find . -not -path './.git/*' -name "*.pyc" -delete
  @rm -rf .ruff_cache
  @echo "All cached files are deleted."

# Lint entire workspace
[group: "Format"]
lint:
  @uv run ruff check .

# Format entire workspace
[group: "Format"]
format:
  @uv run ruff format .

# Backend unit tests
[group: "Test"]
test-unit:
  @uv run --package second-brain pytest apps/backend/tests/unit

# Backend integration tests
[group: "Test"]
test-integration:
  @uv run --package second-brain pytest apps/backend/tests/integration

# Run all backend tests
[group: "Test"]
test:
  @uv run --package second-brain pytest apps/backend/tests

# Run Alembic migrations (requires running postgres via just up-build first)
[group: "DB"]
migrate:
  @cd apps/backend && uv run alembic upgrade head
```

- [ ] **Step 2: Commit**

```bash
git add Justfile
git commit -m "chore: update Justfile with workspace-aware lint/format/test/migrate targets"
```

---

### Task 6: Verify full toolchain

No file changes — this is a verification-only task.

- [ ] **Step 1: Verify lint passes**

```bash
just lint
```

Expected: `All checks passed!` (or lists any pre-existing lint errors to fix)

- [ ] **Step 2: Verify format is clean**

```bash
uv run ruff format --check .
```

Expected: `X files already formatted`

- [ ] **Step 3: Verify backend unit tests pass**

```bash
just test-unit
```

Expected: all existing unit tests pass (same as before restructure)

- [ ] **Step 4: Verify eval package imports backend correctly**

```bash
uv run python -c "import second_brain; print('second_brain import OK')"
uv run python -c "import ragas; print('ragas import OK')"
```

Expected: both lines print `... import OK`. Note: `from second_brain.config import settings` is intentionally avoided here — it triggers pydantic-settings env var validation which requires a populated `.env`.

- [ ] **Step 5: Commit if any lint fixes were needed in Step 1**

```bash
git add -A
git commit -m "fix: resolve lint errors surfaced by ruff"
```

Skip this step if Step 1 passed cleanly.

---

### Task 7: Update documentation

**Files:**
- Modify: `docs/codebase/002-repo-structure.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update docs/codebase/002-repo-structure.md**

Replace the full content:

````markdown
```
pyproject.toml               ← uv workspace root (members: apps/backend, apps/eval)
uv.lock                      ← single workspace lockfile
ruff.toml                    ← shared lint/format config
apps/backend/
  src/second_brain/
    config.py             ← pydantic-settings (Settings); validates all env vars at startup
    main.py               ← FastAPI app + /health
    api/
      routers/            ← endpoint routers (query, ingest)
      schemas.py          ← request/response schemas
    db/
      models.py           ← all 5 SQLModel table definitions (source of truth for types)
      session.py          ← engine + get_session FastAPI dependency
    graphs/               ← LangGraph graph definitions (query graph, ingestion graph)
    nodes/                ← LangGraph node implementations
    services/
      chunking.py         ← hybrid document chunking (headings → paragraphs → sentences)
      embeddings.py       ← Ollama embedding client (qwen3-embedding:0.6b)
      pii.py              ← Presidio PII redaction
      tavily.py           ← Tavily web search/crawl
    observability/
      tracing.py          ← setup_tracing() + @trace_node decorator
  alembic/
    versions/             ← migration files (001_initial_schema.py, ...)
  tests/
    unit/                 ← unit tests (no DB required)
    integration/          ← migration + DB integration tests (requires running postgres)
  pyproject.toml          ← second-brain package (runtime + dev deps)
  pytest.ini              ← backend pytest config (testpaths, asyncio_mode, pythonpath)
  Dockerfile
  alembic.ini
apps/eval/
  pyproject.toml          ← second-brain-eval package (ragas + second-brain workspace dep)
  dataset/                ← curated eval pairs (30–50 after manual curation)
  generate_dataset.py     ← Claude generates ~100 Q&A pairs from ingested docs
  baseline.py             ← no-RAG baseline (Claude only, no retrieval)
  run_eval.py             ← full RAGAS evaluation
  compare.py              ← markdown report with RAG vs baseline delta
temp/
  pending-digest-docs/    ← drop .md files here to ingest
  processed/              ← moved here after successful ingestion
  failed/                 ← moved here after 3 retries exhausted
docker-compose.yml
Justfile
```
````

- [ ] **Step 2: Update CLAUDE.md build section**

Find the `## Build & Verify` section in `CLAUDE.md` and update:

```markdown
## Build & Verify

```bash
just init        # uv sync --all-extras (installs all workspace members + dev tools) + install git hooks (run once)
just up-build    # run backend + Phoenix via Docker Compose (UI at localhost:6006)
just lint        # ruff check across entire workspace
just test-unit   # run apps/backend unit tests
```
```

- [ ] **Step 3: Commit**

```bash
git add docs/codebase/002-repo-structure.md CLAUDE.md
git commit -m "docs: update repo structure and build docs for workspace layout"
```
