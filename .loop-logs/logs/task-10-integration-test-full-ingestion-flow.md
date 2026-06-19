# Task 10: Integration Test — Full Ingestion Flow

**Status:** completed
**Branch:** worktree/task-10-integration-test-full-ingestion-flow
**Commit:** 9fabb9a

## What was done

Created `apps/backend/tests/integration/test_ingestion_graph.py` with 3 integration tests:

1. `test_full_ingest_file_success` — full happy-path: file written to DB, moved to processed/, embeddings 1024-dim, contextual header prepended.
2. `test_duplicate_file_is_skipped_on_reingest` — same MD5 prevents duplicate DB records; embed_text not called on second ingest.
3. `test_api_endpoint_ingest_file_returns_correct_response` — POST /ingest/file returns correct JSON shape.

## Bug fixed

`_do_ingest` in `ingestion_agent.py` was adding `DocumentChunk` rows to the session BEFORE `IngestedDocument`, causing a FK violation on flush. Fixed by inserting `IngestedDocument` first and calling `session.flush()` before the chunk loop.

## Also updated

- `apps/backend/pytest.ini` — registered `integration` marker to avoid pytest warnings.

## Verification

- `just lint` — all checks passed
- `just test-unit` — 71 passed
- Integration tests: 3 passed (against live PostgreSQL via docker compose)
