# Task 12 Log: Integration Tests — AC-5, AC-6, AC-10

## Task Context

### Plan Section

### Task 12: Integration Tests — AC-5, AC-6, AC-10

**Files:**
- Create: `apps/backend/tests/integration/__init__.py`
- Create: `apps/backend/tests/integration/test_query_graph.py`

**Prerequisites:**
- Docker services running: `docker compose up -d app_postgres`
- `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` in `.env` (LLM calls are mocked in these tests)
- `DATABASE_URL` env var pointing to the running test Postgres (same as `settings.app_postgres_url`)

These tests build the real graph with PostgresSaver against a running Postgres instance but mock all LLM + Tavily calls to avoid external API costs and ensure determinism.

- [ ] **Step 1: Write the failing integration tests**

```python
# apps/backend/tests/integration/test_query_graph.py
"""
Integration tests for the query graph.

Acceptance criteria covered:
  AC-5  — PII in user messages is redacted before reaching any LLM node
  AC-6  — PII in final_answer is redacted before being persisted
  AC-10 — sessionId=null creates a new thread; subsequent call with returned UUID7 continues it
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage

from second_brain.core.config import settings
from second_brain.graphs.query_graph import build_query_graph


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _make_routing_mock(decision: str = "neither"):
    m = MagicMock()
    m.routing_decision = decision
    return m


def _make_synthesis_mock(answer: str, confidence: float = 0.85):
    m = MagicMock()
    m.final_answer = answer
    m.confidence = confidence
    return m


# ---------------------------------------------------------------------------
# AC-5: PII is redacted before any LLM node sees the message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_ac5_pii_redacted_before_llm_sees_message():
    """PII in the user message must be stripped before the orchestrator LLM is called."""
    graph = await build_query_graph(settings.app_postgres_url)

    session_id = "ac5-test-session-" + __import__("uuid").uuid4().hex[:8]
    pii_message = "My name is Eleanor Vance and my email is eleanor@secret.com"

    orchestrator_inputs: list[str] = []

    async def capture_orchestrator_invoke(prompt):
        orchestrator_inputs.append(prompt)
        return _make_routing_mock("neither")

    async def mock_synthesis_invoke(prompt):
        return _make_synthesis_mock("Got your message.")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch, \
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth:
        mock_orch.ainvoke = capture_orchestrator_invoke
        mock_synth.ainvoke = mock_synthesis_invoke

        await graph.ainvoke(
            {
                "session_id": session_id,
                "messages": [HumanMessage(content=pii_message)],
                "rag_results": [], "web_results": [], "retrieved_memory": [],
                "routing_decision": "neither", "final_answer": "",
                "confidence": 0.0, "is_uncertain": False,
                "awaiting_correction": False, "awaiting_conflict_clarification": False,
                "conflict_context": [], "fact_updates": [], "correction_updates": [],
            },
            config={"configurable": {"thread_id": session_id}},
        )

    assert len(orchestrator_inputs) == 1
    # The real PII must not appear in what the orchestrator LLM received
    assert "Eleanor Vance" not in orchestrator_inputs[0]
    assert "eleanor@secret.com" not in orchestrator_inputs[0]
    assert "[NAME]" in orchestrator_inputs[0] or "[EMAIL]" in orchestrator_inputs[0]


# ---------------------------------------------------------------------------
# AC-6: PII in final_answer is redacted before being persisted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_ac6_pii_redacted_in_final_answer():
    """PII that appears in the synthesized final_answer must be scrubbed before the graph ends."""
    graph = await build_query_graph(settings.app_postgres_url)

    session_id = "ac6-test-session-" + __import__("uuid").uuid4().hex[:8]

    # LLM synthesis returns an answer that contains PII
    pii_in_answer = "Based on the context, Dr. Marcus Holt at m.holt@hospital.org is your contact."

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch, \
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth:
        mock_orch.ainvoke = AsyncMock(return_value=_make_routing_mock("neither"))
        mock_synth.ainvoke = AsyncMock(return_value=_make_synthesis_mock(pii_in_answer, 0.8))

        result = await graph.ainvoke(
            {
                "session_id": session_id,
                "messages": [HumanMessage(content="Who should I contact?")],
                "rag_results": [], "web_results": [], "retrieved_memory": [],
                "routing_decision": "neither", "final_answer": "",
                "confidence": 0.0, "is_uncertain": False,
                "awaiting_correction": False, "awaiting_conflict_clarification": False,
                "conflict_context": [], "fact_updates": [], "correction_updates": [],
            },
            config={"configurable": {"thread_id": session_id}},
        )

    # Raw PII must be absent from the persisted final_answer
    assert "Marcus Holt" not in result["final_answer"]
    assert "m.holt@hospital.org" not in result["final_answer"]
    assert "[NAME]" in result["final_answer"] or "[EMAIL]" in result["final_answer"]


# ---------------------------------------------------------------------------
# AC-10: sessionId=null creates new thread; UUID7 continues that thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_ac10_null_session_id_creates_new_thread_uuid7_continues():
    """
    First call: sessionId=null → new thread created, UUID7 returned.
    Second call: same UUID7 → graph loads checkpoint, message history has both turns.
    """
    from uuid6 import uuid7
    from second_brain.api.schemas import QueryRequest, QueryResponse
    from second_brain.api.routers.query import query_endpoint

    call_count = [0]

    async def mock_orch(prompt):
        return _make_routing_mock("neither")

    async def mock_synth(prompt):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_synthesis_mock("Turn 1 answer: I see you.")
        else:
            # On turn 2, synthesis should have access to the prior turn in messages
            return _make_synthesis_mock("Turn 2 answer: Continuing our chat.")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm, \
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm, \
         patch("second_brain.api.routers.query._graph", None):
        mock_orch_llm.ainvoke = mock_orch
        mock_synth_llm.ainvoke = mock_synth

        # First call — no sessionId
        response1: QueryResponse = await query_endpoint(
            QueryRequest(message="Hello, start a new session.", sessionId=None)
        )
        assert response1.sessionId is not None
        returned_session_id = response1.sessionId

        # Second call — use returned UUID7 to continue the thread
        response2: QueryResponse = await query_endpoint(
            QueryRequest(message="Continue the conversation.", sessionId=returned_session_id)
        )

    # Both calls must use the same session_id (thread continues)
    assert response2.sessionId == returned_session_id
    assert "Turn 2 answer" in response2.answer
    # Both LLM calls were made (one per turn)
    assert call_count[0] == 2
```

- [ ] **Step 2: Run integration tests to verify they fail**

```bash
cd apps/backend && pytest tests/integration/test_query_graph.py -v -m integration
```

Expected: tests fail (graph not wired correctly, or modules not importable). Fix any import errors before proceeding.

- [ ] **Step 3: Run the full unit + integration test suite**

```bash
cd apps/backend && pytest tests/ -v --tb=short
```

Expected: all unit tests PASS; integration tests that require a running Postgres may be skipped or fail if Postgres is not up. Bring up Postgres first if needed:

```bash
docker compose up -d app_postgres
cd apps/backend && pytest tests/ -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 4: Run all unit tests one final time to confirm nothing regressed**

```bash
cd apps/backend && pytest tests/unit/ -v
```

Expected: all unit tests PASS.

### Acceptance Criteria
- AC-5: PII in user messages is redacted before reaching any LLM node
- AC-6: PII in `final_answer` is redacted before being persisted to `chat_history`
- AC-10: `/query` with a new `sessionId=null` creates a new LangGraph thread; subsequent requests with the returned UUID7 continue the same thread

---

## Attempt 1 — 2026-07-20T05:35:36Z

### Implementation Plan
- Write three failing integration tests at `apps/backend/tests/integration/test_query_graph.py`, adapted from the plan's Step 1 example, importing `settings` from `second_brain.config` (not `second_brain.core.config`) and building the Postgres DSN via `settings.database_url.replace("+psycopg2", "")` (matching the convention in `second_brain.api.routers.query._get_graph`), since those are the actual module paths in this repo.
- Run the new tests against the real, already-migrated Postgres to confirm they exercise real code (not a mocking mistake) before treating any failure as a production bug.
- Run `just lint`, `just test-unit`, and the full integration suite to confirm no regressions.

### Files Changed
- created `apps/backend/tests/integration/test_query_graph.py` — AC-5 (PII redacted before orchestrator LLM), AC-6 (PII redacted in final_answer before return), AC-10 (sessionId=null creates new thread; returned UUID7 continues it) integration tests against the real query graph + Postgres, with all Anthropic LLM calls mocked

### New Tests
- `test_ac5_pii_redacted_before_llm_sees_message`
- `test_ac6_pii_redacted_in_final_answer`
- `test_ac10_null_session_id_creates_new_thread_uuid7_continues`

### Key Decisions
- **Real bug found and worked around in the test, not papered over.** The first run of every test failed with `psycopg.errors.ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`. Root cause: `build_query_graph()` (apps/backend/src/second_brain/graphs/query_graph.py, from an earlier merged task) constructs `AsyncPostgresSaver` on top of a bare `AsyncConnectionPool(conninfo=postgres_url, open=False)`, whose connections default to `autocommit=False`. `AsyncPostgresSaver.setup()` issues `CREATE INDEX CONCURRENTLY`, which Postgres refuses to run inside a transaction — so the very first call to `build_query_graph()` against a database that doesn't yet have the LangGraph checkpoint tables always fails. This reproduces independent of any mocking in these tests; it is a latent bug in already-merged production code, not something introduced by this task.
  Worked around it inside the test file only (no production code touched, per task scope): added `_ensure_checkpoint_tables_exist()` / an autouse fixture that first runs `AsyncPostgresSaver.from_conn_string(...).setup()` — that classmethod opens its own connection with `autocommit=True`, so the migration (including `CREATE INDEX CONCURRENTLY`) succeeds once and records the applied version in `checkpoint_migrations`. Every subsequent `setup()` call — including the one `build_query_graph()` performs against the buggy pool — then finds nothing left to migrate and is a no-op, so the tests pass without changing `query_graph.py`.
  **Flagging prominently for follow-up:** `query_graph.py::build_query_graph` will break on any fresh database (e.g. a new environment, CI, or a wiped dev DB) until checkpoint tables happen to pre-exist. The real fix is passing `kwargs={"autocommit": True}` to `AsyncConnectionPool(...)` in `build_query_graph()`, or calling `checkpointer.setup()` via a short-lived `autocommit=True` connection before handing the pool-backed saver to the compiled graph. Not fixed here since this task's scope is tests only.
- Used a fresh `uuid4().hex[:8]`-suffixed `thread_id`/`session_id` per test (as instructed) so the three tests, and repeated runs against the same live Postgres, never collide on the same checkpoint rows.

### Lint Output
PASS

### Test Output
PASS (131 unit tests passed, 0 regressions; 6 integration tests passed — 3 new AC-5/AC-6/AC-10 tests + 3 pre-existing ingestion-graph integration tests, 3 new)

### Commit
`d7c7e6c`

### Outcome: success
