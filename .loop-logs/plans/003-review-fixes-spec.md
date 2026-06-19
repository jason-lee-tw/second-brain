# Spec: Review Fix Tasks for feat/003-ingestion

## Context

These are targeted fixes for the four 🟡 findings from the enhanced-review of the
ingestion pipeline branch (feat/003-ingestion). No new features are being added.
All changes are surgical — rename one function, tighten one type, add two aclose()
calls, add one comment.

## Architecture

- Backend: FastAPI + LangGraph + SQLModel + Ollama + Anthropic (claude-haiku)
- `apps/backend/src/second_brain/` is the main package (imports rooted at `src/`)
- Services live in `services/`, nodes in `nodes/`, graphs in `graphs/`, API in `api/`
- Tests: unit under `tests/unit/`, integration under `tests/integration/`
- Run commands: `just lint`, `just test-unit`, `just format`

## Key Files

- `apps/backend/src/second_brain/services/tavily.py` — Tavily crawl service
- `apps/backend/src/second_brain/api/routers/ingest.py` — ingest router
- `apps/backend/src/second_brain/api/schemas.py` — Pydantic request/response models
- `apps/backend/src/second_brain/main.py` — FastAPI app + lifespan
- `apps/backend/src/second_brain/services/embeddings.py` — Ollama httpx client
- `apps/backend/src/second_brain/nodes/ingestion_agent.py` — LangGraph node

## Constraints

- Do NOT change any public API response shape (IngestFileResponse fields stay the same)
- Do NOT change any DB schema
- AnyHttpUrl in Pydantic v2 serializes as a URL object; if router/tests pass the value
  to Tavily, call `str(url)` to convert back to string
- The lifespan in main.py uses a try/except for TracerProvider shutdown — use the same
  broad-except + exc_info=True pattern for aclose() calls to be consistent
