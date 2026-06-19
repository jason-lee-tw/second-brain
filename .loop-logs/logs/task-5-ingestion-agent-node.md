# Task 5: Ingestion Agent Node — Completion Log

**Date**: 2026-06-19
**Branch**: worktree/task-5-ingestion-agent-node
**Worktree**: .worktrees/task-5-ingestion-agent-node
**Commit**: 2a9c36f

## What Was Done

Created the `ingestion_agent_node` LangGraph node for the ingestion pipeline.

### Files Created

- `apps/backend/src/second_brain/nodes/ingestion_agent.py` — Implementation
- `apps/backend/tests/unit/test_nodes/__init__.py` — Package init
- `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py` — Tests (TDD)

### Implementation Summary

The node:
1. Takes the first item from `in_progress` state
2. Reads the markdown file from `PENDING_DOCS_DIR`
3. Computes MD5 hash for deduplication check against `IngestedDocument` table
4. If duplicate: skips embedding, moves file to `PROCESSED_DIR`, marks processed
5. If new: chunks via `chunk_document`, generates contextual header via Claude Haiku, embeds via `embed_text`, stores `DocumentChunk` and `IngestedDocument` rows
6. On success: returns updated `processed` list, clears `in_progress`
7. On failure (retry_count < 3): adds to `retry_queue` with incremented count
8. On terminal failure (retry_count >= 3): moves file to `FAILED_DIR`, adds to `failed` list

### Key Implementation Detail

Used `chunk_metadata=chunk.metadata` (NOT `metadata=...`) when constructing `DocumentChunk` — required to avoid SQLAlchemy internals conflict per project CLAUDE.md.

## Test Results

- 4 new tests written (TDD: tests written before implementation)
- All 4 pass after implementation
- Full suite (59 tests) continues to pass
- `just lint` passes with no errors

## Test Coverage

1. `test_successful_ingest_moves_file_to_processed` — happy path
2. `test_duplicate_file_is_skipped_and_moved_to_processed` — dedup path
3. `test_first_failure_goes_to_retry_queue` — first failure → retry_count=1
4. `test_third_failure_moves_to_failed_and_moves_file` — terminal failure → failed list + file move
