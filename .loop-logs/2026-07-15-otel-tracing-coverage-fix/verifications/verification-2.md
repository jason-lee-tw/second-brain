# Verification — Round 2

**Spec:** docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md
**Outcome:** pass

## Verified

| AC | Result | Evidence |
|----|--------|----------|
| AC1 — lint/format/type-check clean | PASS | `just lint` all checks passed; `just format` 113 files unchanged; `just type-check` 0 errors/0 warnings |
| AC2 — `just test-unit` passes | PASS | 225 passed, 2 warnings |
| AC3 — `/query` named node spans + httpx/asyncpg/SQLAlchemy children | PASS | Trace `06cddfa5ffb8e82109b58ca1a51dba55`: `memory_persistence` has child `INSERT second_brain` with `db.statement='INSERT INTO learned_facts (...)'` — the previously-missing write span. Also `connect`, `SELECT` (asyncpg conflict check), `POST` (Ollama embeddings). Trace `e00b2bd6b5eb639ac3e5083ff1bcbad4` shows `rag_retrieval` node span with httpx + asyncpg children. |
| AC4 — `/ingest/file` `ingest` span (no `pick_file`), embedding + DB write children | PASS | Trace `515502ddc7152998b84fe247317d3100`: `ingest` span present, no sibling `pick_file` trace_node span. Children: `INSERT second_brain` × 2 (`document_chunks`, `ingested_documents`), `SELECT` (dedup check), `connect` × 2, httpx POST to Ollama embeddings and Anthropic. |

## Round-1 fix re-verified

`tracing.py` now calls `SQLAlchemyInstrumentor().instrument(engine=engine)`. Live trace
confirms real `INSERT`/write spans with actual `db.statement` text now appear — not just
the harmless `connect` span from round 1.

**No regressions** — node spans, httpx, asyncpg all still correct.
