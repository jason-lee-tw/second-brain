# Task 2: Hybrid Chunking Service — Attempt 1

**Status:** completed
**Branch:** worktree/task-2-hybrid-chunking-service
**Worktree:** .worktrees/task-2-hybrid-chunking-service

## Outcome

- Implemented `apps/backend/src/second_brain/services/chunking.py` with:
  - `detect_content_type()` — returns `"article"` if H1/H2/H3 headings found, else `"transcription"`
  - `chunk_document()` — hybrid strategy: headings → paragraphs → sentences; code fences protected as atomic units
  - `Chunk` dataclass with `content`, `chunk_index`, `metadata` (source, heading_path, content_type, char_count)
  - Separate token budgets for articles (target=512, max=1024, overlap=64) vs transcriptions (target=256, max=512, overlap=0)
- Created `apps/backend/tests/unit/test_services/test_chunking.py` with 15 tests covering:
  - Content-type detection (H1, H2, no-heading)
  - Chunk dataclass return types
  - Heading path construction (flat, nested, reset on new level)
  - Sequential chunk indices
  - Metadata fields (source, char_count, content_type)
  - Code fence atomicity (single and multiple fences)
  - Pre-heading preamble capture
  - Empty input edge case

## Test Results

- `just lint` — All checks passed
- `just test-unit` — 44 passed (15 new + 29 existing)

## Commit

`62dfbf6` feat(ingestion): add hybrid chunking service with code fence protection
