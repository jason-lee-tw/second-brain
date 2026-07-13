# Personal Second Brain

## Project

A personal "Second Brain" knowledge management system. Ingests content from local markdown files and web URLs, stores it for semantic retrieval, and maintains persistent memory of conversations and learned facts. Evaluated with RAGAS to prove measurable improvement over a no-RAG baseline.

**Endpoints** (backend at `localhost:3001` via Docker Compose)**:**

- `POST /query` — chat with the Second Brain (returns answer + confidence + session continuity)
- `POST /ingest/file` — process `.md` files from `temp/pending-digest-docs/`
- `POST /ingest/url` — crawl URL(s) via Tavily, save as markdown, then ingest

**Phoenix is running on `localhost:6006` via Docker Compose.**

### Tech Stack

Refer to [001-techstack.md](./docs/codebase/001-tech-stack.md).

## Documentation Index

Each `docs/` subfolder has a `000-index.md` with a one-sentence summary of every document — start there to find relevant context fast:

- [docs/business/000-index.md](./docs/business/000-index.md) — requirements, PRD, implementation plan, workflow diagrams
- [docs/codebase/000-index.md](./docs/codebase/000-index.md) — tech stack, repo structure, system architecture, database schema
- [docs/bugs/000-index.md](./docs/bugs/000-index.md) — documented bugs and their root-cause decisions

## Structure

Refer to [002-repo-structure.md](./docs/codebase/002-repo-structure.md).

**Key patterns:**

- Two separate LangGraph graphs: `SecondBrainState` (query) and `IngestionState` (ingestion) — share no runtime state; separating them keeps state schemas clean.
- `DocumentChunk` uses Python attribute `chunk_metadata` mapped to SQL column `metadata` — avoids SQLAlchemy name conflict. Use `.chunk_metadata` in Python; use `metadata` in raw SQL.
- `ModelCorrection.embedding` encodes the `correction` field, NOT `original_answer` — so cosine similarity retrieval surfaces the correct answer, not the mistake.
- Backend never joins `phoenix_network` — OTEL traces reach Phoenix via host port 6006 only. On Linux Docker hosts, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the backend service.
- Imports are rooted at `src/` via `pythonpath = src` in `apps/backend/pytest.ini`, e.g. `from second_brain.config import settings`.
- Dockerfiles live in `docker/` named `Dockerfile.<service>` (e.g. `Dockerfile.backend`) — each service's build context remains its own app directory (`apps/<service>/`).
- Two Postgres connection pools coexist: `asyncpg.Pool` in `db/pool.py` (shared by `rag_retrieval` and `memory_retrieval_node` via `get_pgvector_pool()`) and `psycopg_pool.AsyncConnectionPool` in `graphs/query_graph.py` (required by LangGraph's `AsyncPostgresSaver`). They cannot share a pool — different drivers.

## Build & Verify

```bash
just init        # uv sync --all-extras (installs all workspace members + dev tools) + install git hooks (run once)
just up-all      # Start Ollama and run all other services via Docker Compose
just down-all    # Stop Ollama and all other services via Docker Compose
just down-clean  # Stop all services (except Ollama) and clear all volumes via Docker Compose
just lint        # ruff check across entire workspace
just test-unit   # run apps/backend unit tests
just type-check  # run apps/backend type check
```

TDD is expected: new code ships with tests for the happy path and 2+ edge cases (see Done Means).

## Critical Rules

- NEVER commit directly to `main`, ALWAYS create a branch follow format in [branch-name-rule.md](./.claude/rules/branch-name-rule.md)
- Do NOT suppress errors with broad excepts — fix the root cause
  (exception: teardown paths may catch-and-log broad exceptions with
  exc_info=True when the exception is unactionable at exit time)
- Do NOT install dependencies without flagging it first (use `uv add`, NEVER edit lockfiles by hand)
- Commits MUST follow Conventional Commits (enforced by `.hooks/commit-msg`)

## Done Means

ALWAYS verify before claiming a task done/fixed/verified — passing tests are necessary
but NOT sufficient. A task is complete only when ALL hold:

1. `just lint` and `just format` pass with no changes.
2. `just type-check` pass without any error and warning.
3. `just test-unit` passes (TDD — write a failing test first; new code ships with tests
   for the happy path and 2+ edge cases).
4. Behavior is observed on the running system, not just inferred. For any change with
   runtime behavior (backend, HTTP, DB, agent, tracing): boot it (`just up-all` or
   `uvicorn`), exercise the actual path, and confirm the observed output (HTTP status,
   response body, log line, trace) matches the acceptance criteria.
5. Implementation is reviewed and clear all issues raised by using skill `enhanced-review`.

Do NOT say "done", "fixed", "verified", or "works" without that evidence in hand. If
runtime behavior can't be observed, say so and name the blocker — never assume.

## Compaction

When compacting, preserve: modified file list, failing test/lint output, the current
plan, and any decisions made explicitly this session.

## Handoff document

When handing job to next agent (non subagent), ALWAYS write the detailed context into a handoff file. So the next agent can get enough context from the handoff file.

Store the hand-off file into [Claude temp folder](./.claude/temp/)
