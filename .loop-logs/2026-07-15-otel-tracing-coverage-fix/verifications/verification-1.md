# Verification — Round 1

**Spec:** docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md
**Outcome:** fail

## Verified

| AC | Result | Evidence |
|----|--------|----------|
| AC1 — lint/format/type-check clean | PASS | `just lint` all checks passed; `just format` 113 files unchanged; `just type-check` 0 errors/0 warnings |
| AC2 — `just test-unit` passes | PASS | 225 passed, 2 warnings |
| AC3 — named node spans nested under HTTP span | PASS | Trace `4f741b41d659805493508c006390cb52`: `memory_retrieval_node`, `orchestrator`, `synthesis`, `memory_agent`, `memory_persistence` all direct children of root `POST /query` span. Trace `9dd771d4777aa18ae6a2eb6c5b47a6fe` additionally shows `rag_retrieval`. |
| AC3 — httpx child span (Ollama embeddings) | PASS | `POST` spans under `memory_retrieval_node`/`memory_persistence`/`rag_retrieval` with `http.url=http://host.docker.internal:11434/api/embeddings` |
| AC3 — asyncpg child span (pgvector reads) | PASS | `SELECT` spans under `memory_retrieval_node`/`memory_persistence` with `db.statement` querying `learned_facts`/`model_corrections` via cosine distance, `db.system=postgresql` |
| AC3 — SQLAlchemy child span (writes) | **FAIL** | `memory_persistence` children: `POST` (embed), 2× `SELECT` (asyncpg), `connect` (SQLAlchemy `Engine.connect` patch only). No SELECT/INSERT span for the `learned_facts` write anywhere in the trace, despite the row existing in Postgres (`c1c0421f-...`, `created_at=2026-07-15 07:17:53`, inside the trace window). |
| AC4 — `ingest` span present, no `pick_file` span, embedding/DB children | **FAIL** | `ingest` span present as direct child of root; no `pick_file` span in the `trace_node` namespace (correct). `POST` to Ollama embeddings nested inside `ingest` (PASS). But no INSERT/SELECT span for `document_chunks` despite the row existing (`f1142cd4-...`, inside trace window). Same root cause as AC3. |

## Root cause

`SQLAlchemyInstrumentor().instrument()` in `apps/backend/src/second_brain/observability/tracing.py`
is called with no arguments. Per the installed library source
(`opentelemetry/instrumentation/sqlalchemy/__init__.py:270-278`), a per-statement
`EngineTracer` (the thing that hooks `before_cursor_execute`/`after_cursor_execute` to
emit SELECT/INSERT spans) is only attached when `engine=`/`engines=` is passed
explicitly — a bare call only patches the `create_engine` factory functions and
`Engine.connect` at the class level. `second_brain/db/session.py`'s module-level
`engine = create_engine(...)` is constructed at import time (before `setup_tracing()`
runs in the FastAPI lifespan), so even the wrapped-factory path never applies to it
either.

## Fix

Import `engine` from `second_brain.db.session` in `tracing.py` and call
`SQLAlchemyInstrumentor().instrument(engine=engine)`.
