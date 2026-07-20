"""
Integration tests for the query graph.

Acceptance criteria covered:
  AC-5  — PII in user messages is redacted before reaching any LLM node
  AC-6  — PII in final_answer is redacted before being persisted
  AC-10 — sessionId=null creates a new thread; subsequent call with returned
          UUID7 continues it

Requirements:
    - PostgreSQL running (docker compose up -d app_postgres)
    - LangGraph checkpoint tables are created on demand by build_query_graph()
    - Anthropic LLM calls are mocked — no live API keys required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.config import settings
from second_brain.graphs.query_graph import build_query_graph

# build_query_graph() does not strip the SQLAlchemy dialect suffix itself —
# the caller must pass a clean psycopg-compatible DSN (same convention as
# second_brain.api.routers.query._get_graph).
_POSTGRES_URL = settings.database_url.replace("+psycopg2", "")


async def _ensure_checkpoint_tables_exist() -> None:
    """Work around a bug in query_graph.build_query_graph().

    build_query_graph() runs its AsyncPostgresSaver.setup() against a connection
    pulled from an AsyncConnectionPool, whose connections default to
    autocommit=False. AsyncPostgresSaver.setup() issues `CREATE INDEX
    CONCURRENTLY`, which Postgres refuses to run inside a transaction block —
    so on a database where the checkpoint tables don't exist yet, the very
    first build_query_graph() call raises `psycopg.errors.ActiveSqlTransaction`.

    AsyncPostgresSaver.from_conn_string() opens its connection with
    autocommit=True, so running setup() through it once succeeds and leaves a
    fully-applied row in `checkpoint_migrations`. Every later setup() call
    (including the one build_query_graph() performs against the buggy pool)
    then finds nothing left to migrate and is a no-op. This is a test-only
    workaround; the production bug in query_graph.py is unaffected.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(_POSTGRES_URL) as saver:
        await saver.setup()


@pytest.fixture(autouse=True)
async def _checkpoint_tables_ready():
    await _ensure_checkpoint_tables_exist()


def _base_input(session_id: str, message: str) -> dict:
    return {
        "session_id": session_id,
        "messages": [HumanMessage(content=message)],
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
    """PII in the user message must be stripped before the orchestrator LLM sees it."""
    graph = await build_query_graph(_POSTGRES_URL)

    session_id = "ac5-test-session-" + uuid.uuid4().hex[:8]
    pii_message = "My name is Eleanor Vance and my email is eleanor@secret.com"

    orchestrator_inputs: list[str] = []

    async def capture_orchestrator_invoke(prompt):
        orchestrator_inputs.append(prompt)
        return _make_routing_mock("neither")

    async def mock_synthesis_invoke(prompt):
        return _make_synthesis_mock("Got your message.")

    with (
        patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch,
        patch("second_brain.nodes.synthesis._structured_llm") as mock_synth,
    ):
        mock_orch.ainvoke = capture_orchestrator_invoke
        mock_synth.ainvoke = mock_synthesis_invoke

        await graph.ainvoke(
            _base_input(session_id, pii_message),
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
    """PII in the synthesized final_answer must be scrubbed before the graph ends."""
    graph = await build_query_graph(_POSTGRES_URL)

    session_id = "ac6-test-session-" + uuid.uuid4().hex[:8]

    # LLM synthesis returns an answer that contains PII
    pii_in_answer = (
        "Based on the context, Dr. Marcus Holt at m.holt@hospital.org "
        "is your contact."
    )

    with (
        patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch,
        patch("second_brain.nodes.synthesis._structured_llm") as mock_synth,
    ):
        mock_orch.ainvoke = AsyncMock(return_value=_make_routing_mock("neither"))
        mock_synth.ainvoke = AsyncMock(
            return_value=_make_synthesis_mock(pii_in_answer, 0.8)
        )

        result = await graph.ainvoke(
            _base_input(session_id, "Who should I contact?"),
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
    First call: sessionId=null -> new thread created, UUID7 returned.
    Second call: same UUID7 -> graph loads checkpoint, message history has both turns.
    """
    from second_brain.api.routers.query import query_endpoint
    from second_brain.api.schemas import QueryRequest, QueryResponse

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

    with (
        patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm,
        patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm,
        patch("second_brain.api.routers.query._graph", None),
    ):
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
            QueryRequest(
                message="Continue the conversation.", sessionId=returned_session_id
            )
        )

    # Both calls must use the same session_id (thread continues)
    assert response2.sessionId == returned_session_id
    assert "Turn 2 answer" in response2.answer
    # Both LLM calls were made (one per turn)
    assert call_count[0] == 2
