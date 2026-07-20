# Task 10 Log: API Schemas and `/query` Router

## Task Context

### Plan Section
### Task 10: API Schemas and `/query` Router

**Files:**
- Modify: `apps/backend/src/second_brain/api/schemas.py`
- Create: `apps/backend/src/second_brain/api/routers/query.py`

**Dependencies:** `pip install uuid6` (provides `uuid7()`).

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_query_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from second_brain.api.schemas import QueryRequest, QueryResponse


def test_query_request_with_null_session_id():
    req = QueryRequest(message="Hello", sessionId=None)
    assert req.message == "Hello"
    assert req.sessionId is None


def test_query_request_with_session_id():
    req = QueryRequest(message="Hello", sessionId="01900000-0000-7000-8000-000000000001")
    assert req.sessionId == "01900000-0000-7000-8000-000000000001"


def test_query_response_shape():
    resp = QueryResponse(
        answer="The answer is 42.",
        sessionId="01900000-0000-7000-8000-000000000001",
        confidence=0.88,
        isUncertain=False,
        conflictDetected=False,
        conflictContext=[],
    )
    assert resp.answer == "The answer is 42."
    assert resp.isUncertain is False
    assert resp.conflictDetected is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_query_router.py -v
```

Expected: `ImportError` — `QueryRequest`/`QueryResponse` not in schemas yet.

- [ ] **Step 3: Add schemas to `api/schemas.py`**

Open `apps/backend/src/second_brain/api/schemas.py` and append the following (keep all existing ingestion schemas):

```python
# --- append to apps/backend/src/second_brain/api/schemas.py ---

from typing import Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None  # UUID7 or null for new session


class QueryResponse(BaseModel):
    answer: str
    sessionId: str        # UUID7 — use this in the next call to continue the session
    confidence: float     # 0.0–1.0
    isUncertain: bool     # True when confidence < 0.7; prompts user to optionally correct
    conflictDetected: bool  # True when a new fact conflicts with existing memory
    conflictContext: list[str]  # Descriptions of detected conflicts, if any
```

- [ ] **Step 4: Create the `/query` router**

```python
# apps/backend/src/second_brain/api/routers/query.py
from uuid6 import uuid7
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from second_brain.api.schemas import QueryRequest, QueryResponse
from second_brain.core.config import settings
from second_brain.graphs.query_graph import build_query_graph

router = APIRouter(prefix="/query", tags=["query"])

# Module-level compiled graph singleton — initialised once on first request
_graph = None


async def _get_graph():
    global _graph
    if _graph is None:
        _graph = await build_query_graph(settings.app_postgres_url)
    return _graph


@router.post("", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest) -> QueryResponse:
    """Chat with the Second Brain.

    - sessionId=null → creates a new conversation thread (new UUID7 returned)
    - sessionId=<UUID7> → continues an existing thread (history loaded from checkpoint)

    PII in the message is redacted before reaching any LLM node (AC-5).
    PII in the final answer is redacted before being persisted (AC-6).
    """
    session_id: str = request.sessionId or str(uuid7())

    graph = await _get_graph()

    # Pass the new user message; LangGraph's add_messages reducer appends it
    # to the existing checkpoint history for this thread_id (AC-10)
    input_state = {
        "session_id": session_id,
        "messages": [HumanMessage(content=request.message)],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    config = {"configurable": {"thread_id": session_id}}

    try:
        result = await graph.ainvoke(input_state, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query graph error: {exc}") from exc

    conflict_context: list[str] = result.get("conflict_context", [])

    return QueryResponse(
        answer=result["final_answer"],
        sessionId=session_id,
        confidence=result["confidence"],
        isUncertain=result["is_uncertain"],
        conflictDetected=bool(conflict_context),
        conflictContext=conflict_context,
    )
```

- [ ] **Step 5: Run schema tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_query_router.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/api/schemas.py \
  src/second_brain/api/routers/query.py \
  tests/unit/test_query_router.py
git commit -m "feat(api): add QueryRequest/QueryResponse schemas and POST /query router"
```

### Acceptance Criteria
- AC-10: `/query` with a new `sessionId=null` creates a new LangGraph thread; subsequent requests with the returned UUID7 continue the same thread

---

## Attempt 1 — 2026-07-20T05:22:15Z

### Implementation Plan
- Write failing schema tests (append to `test_schemas.py`): null sessionId, explicit sessionId, default sessionId, response shape, response with conflict context
- Write failing router tests (new `test_routers/test_query.py`): null-sessionId generates new thread_id, existing sessionId is reused, response field mapping, conflictDetected derivation — build a standalone `FastAPI()` app wrapping only `query_router` since `main.py` registration is Task 11's job
- Run tests to confirm ImportError then ModuleNotFoundError
- Append `QueryRequest`/`QueryResponse` to `schemas.py`; create `api/routers/query.py` per plan Step 4, adjusted for this repo's `settings.database_url.replace("+psycopg2", "")` DSN convention and a best-effort `shutdown()` reaching the pool via `_graph.checkpointer.conn`
- Run `just lint` and `just test-unit`, fix any line-length violations

### Files Changed
- modified `apps/backend/src/second_brain/api/schemas.py` — appended `QueryRequest`/`QueryResponse` pydantic models
- created `apps/backend/src/second_brain/api/routers/query.py` — `POST /query` router, `_get_graph()` singleton accessor, `shutdown()` for pool cleanup
- modified `apps/backend/tests/unit/test_api/test_schemas.py` — appended `QueryRequest`/`QueryResponse` tests
- created `apps/backend/tests/unit/test_api/test_routers/test_query.py` — router tests mocking `second_brain.api.routers.query._get_graph`

### New Tests
- `test_query_request_with_null_session_id`
- `test_query_request_with_session_id`
- `test_query_request_session_id_defaults_to_none`
- `test_query_response_shape`
- `test_query_response_with_conflict_context`
- `test_query_with_null_session_id_generates_new_thread_id`
- `test_query_with_existing_session_id_reuses_thread_id`
- `test_query_response_maps_graph_state_to_response_shape`
- `test_query_response_reports_conflict_detected_when_conflict_context_present`

### Key Decisions
- `build_query_graph()` never returns the `AsyncConnectionPool` it opens internally, and it isn't modified for this task — `shutdown()` reaches the pool via `_graph.checkpointer.conn` (the `AsyncPostgresSaver` stores the pool it was constructed with as `.conn`), guarded by `getattr` so it degrades to a no-op if that internal shape ever changes.
- Router tests mock `_get_graph` (rather than patching a module-level `_graph` object directly) because the singleton is lazily built inside the request path — patching the accessor function is the smallest surface that fully bypasses the real `build_query_graph()`/Postgres dependency.
- Router tests build a standalone `FastAPI()` app around just `query_router` instead of importing `second_brain.main.app`, since the router is not yet registered on the main app (that wiring is explicitly Task 11's responsibility, not this task's).
- `just format` also reformatted three unrelated pre-existing test files (`test_rag_retrieval.py`, `test_web_research.py`, `test_tavily.py`) due to ruff version drift unrelated to this change; reverted those to keep the diff scoped to this task.

### Lint Output
PASS

### Test Output
PASS (130 passed, 9 new)

### Commit
`5930d60`

### Outcome: success
