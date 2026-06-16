# investment-report-app

## Project

A personal "Second Brain" knowledge management system. Ingests content from local markdown files and web URLs, stores it for semantic retrieval, and maintains persistent memory of conversations and learned facts. Evaluated with RAGAS to prove measurable improvement over a no-RAG baseline.

**Endpoints:**

- `POST /query` — chat with the Second Brain (returns answer + confidence + session continuity)
- `POST /ingest/file` — process `.md` files from `temp/pending-digest-docs/`
- `POST /ingest/url` — crawl URL(s) via Tavily, save as markdown, then ingest

### Tech Stack

| Component            | Technology                                                                         |
| -------------------- | ---------------------------------------------------------------------------------- |
| Language             | Python 3.12                                                                        |
| Web framework        | FastAPI                                                                            |
| Agent orchestration  | LangGraph                                                                          |
| Database             | PostgreSQL 16 + pgvector                                                           |
| ORM + migrations     | SQLModel + Alembic                                                                 |
| Observability        | Arize Phoenix (OTEL) — UI at `localhost:6006`                                      |
| Embedding model      | `qwen3-embedding:0.6b` via Ollama (`localhost:11434`, dim=1024)                    |
| LLM — lightweight    | `claude-haiku-4-5` (routing, web research, memory extraction)                      |
| LLM — synthesis/eval | `claude-sonnet-4-6` (final answers + LLM-as-judge evals)                           |
| Web search/crawl     | Tavily SDK                                                                         |
| PII redaction        | Presidio (broad scope — names, emails, phones, addresses, IDs, financial, medical) |
| Evaluation           | RAGAS (`context_recall`, `context_precision`, `faithfulness`, `answer_relevancy`)  |
| Containerisation     | Docker Compose                                                                     |

## Structure

```
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
  pyproject.toml
  Dockerfile
  alembic.ini
eval/
  generate_dataset.py     ← Claude generates ~100 Q&A pairs from ingested docs
  baseline.py             ← no-RAG baseline (Claude only, no retrieval)
  run_eval.py             ← full RAGAS evaluation
  compare.py              ← markdown report with RAG vs baseline delta
  dataset/                ← curated eval pairs (30–50 after manual curation)
temp/
  pending-digest-docs/    ← drop .md files here to ingest
  processed/              ← moved here after successful ingestion
  failed/                 ← moved here after 3 retries exhausted
docker-compose.yml
Justfile
```

**Key patterns:**

- Two separate LangGraph graphs: `SecondBrainState` (query) and `IngestionState` (ingestion) — share no runtime state; separating them keeps state schemas clean.
- `DocumentChunk` uses Python attribute `chunk_metadata` mapped to SQL column `metadata` — avoids SQLAlchemy name conflict. Use `.chunk_metadata` in Python; use `metadata` in raw SQL.
- `ModelCorrection.embedding` encodes the `correction` field, NOT `original_answer` — so cosine similarity retrieval surfaces the correct answer, not the mistake.
- Backend never joins `phoenix_network` — OTEL traces reach Phoenix via host port 6006 only. On Linux Docker hosts, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the backend service.
- Imports are rooted at `src/` via `pythonpath = ["src"]` in `pyproject.toml`, e.g. `from second_brain.config import settings`.

## Build & Verify

```bash
just init        # uv sync + install git hooks (run once)
just up-build    # run backend + Langfuse via Docker Compose (UI at localhost:6006)
```

TDD is expected: new code ships with tests for the happy path and 2+ edge cases (see Done Means).

## Critical Rules

- Do NOT commit directly to `main`, ALWAYS create a branch follow format `<category>/<ticket_number_or_000>-<description>`
- Do NOT suppress errors with broad excepts — fix the root cause
- Do NOT install dependencies without flagging it first (use `uv add`, never edit lockfiles by hand)
- Commits MUST follow Conventional Commits (enforced by `.hooks/commit-msg`)

## Done Means

ALWAYS verify before claiming a task done/fixed/verified — passing tests are necessary
but NOT sufficient. A task is complete only when ALL hold:

1. `just lint` and `just format` pass with no changes.
2. `just test-unit` passes (TDD — write a failing test first; new code ships with tests
   for the happy path and 2+ edge cases).
3. Behavior is observed on the running system, not just inferred. For any change with
   runtime behavior (backend, HTTP, DB, agent, tracing): boot it (`just up-build` or
   `uvicorn`), exercise the actual path, and confirm the observed output (HTTP status,
   response body, log line, trace) matches the acceptance criteria.

Do NOT say "done", "fixed", "verified", or "works" without that evidence in hand. If
runtime behavior can't be observed, say so and name the blocker — never assume.

## Compaction

When compacting, preserve: modified file list, failing test/lint output, the current
plan, and any decisions made explicitly this session.
