# Task 7: Remaining Nodes + Ingest Router

## Status: COMPLETED

## Worktree
`.worktrees/task-7-remaining-nodes-ingest-router`  
Branch: `worktree/task-7-remaining-nodes-ingest-router`

## Changes Made

### Fix 1: pii_redaction.py
- Added imports: `RedactInboundOutput`, `RedactOutboundOutput` from state, `get_str_content` from utils
- Changed `redact_inbound` return type from `dict` to `RedactInboundOutput`
- Changed `redact_pii(last.content)` to `redact_pii(get_str_content(last))`
- Changed `redact_outbound` return type from `dict` to `RedactOutboundOutput`
- Fixed lint: split long import line using parentheses

### Fix 2: rag_retrieval.py
- Added imports: `cast` from typing, `RagResult`, `RagRetrievalOutput` from state, `get_str_content` from utils
- Changed `_query_pgvector` return type from `list[dict]` to `list[RagResult]`
- Wrapped metadata value with `cast("dict[str, str | int]", ...)`
- Changed `retrieve_from_rag` return type from `dict` to `RagRetrievalOutput`
- Changed `state["messages"][-1].content` to `get_str_content(state["messages"][-1])`
- Fixed lint: split long cast line across multiple lines

### Fix 3: web_research.py
- Added imports: `WebResearchOutput` from state, `get_str_content` from utils
- Changed `search_web` return type from `dict` to `WebResearchOutput`
- Changed `state["messages"][-1].content` to `get_str_content(state["messages"][-1])`

### Fix 4: memory_retrieval.py
- Added import: `RetrieveMemoryOutput` from state
- Changed `retrieve_memory` return type from `dict` to `RetrieveMemoryOutput`

### Fix 5: api/routers/ingest.py
- Changed `isinstance(result, Exception)` to `isinstance(result, BaseException)` (line 62)
  to correctly catch all exceptions from `asyncio.gather(return_exceptions=True)`

## Verification

- `just lint`: All checks passed
- `just test-unit`: 165 passed, 2 warnings
- Commit: `02d808f fix(types): get_str_content and typed returns across remaining nodes`
