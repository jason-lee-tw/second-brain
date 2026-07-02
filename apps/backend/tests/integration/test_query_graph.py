"""Integration tests for the query graph — AC-5, AC-6, AC-10.

These tests verify the real LangGraph wiring with mocked LLM calls and a
MemorySaver checkpointer (no live Postgres or Anthropic API required).

Markers
-------
- @pytest.mark.integration  (not collected by ``just test-unit``)

Run explicitly with:
    pytest -m integration apps/backend/tests/integration/test_query_graph.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mem_saver() -> MemorySaver:
    """Return a MemorySaver with a no-op async setup() shim.

    build_query_graph() calls ``await checkpointer.setup()`` which
    MemorySaver does not provide by default.
    """
    saver = MemorySaver()
    saver.setup = AsyncMock()  # type: ignore[attr-defined]
    return saver


def _mock_saver_factory(saver: MemorySaver) -> MagicMock:
    """Return a callable mock that yields *saver* regardless of arguments."""
    return MagicMock(return_value=saver)


def _base_input_state(message: str, session_id: str = "test-session") -> dict:
    """Build a minimal SecondBrainState input dict for testing."""
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
    }


def _mock_routing(decision: str = "neither") -> MagicMock:
    routing = MagicMock()
    routing.routing_decision = decision
    return routing


def _mock_synthesis(answer: str, confidence: float = 0.9) -> MagicMock:
    synth = MagicMock()
    synth.final_answer = answer
    synth.confidence = confidence
    synth.reasoning = "mocked for test"
    return synth


# ---------------------------------------------------------------------------
# AC-5: PII is redacted inbound (LLM never sees raw PII in the message)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ac5_pii_redacted_before_llm_sees_message():
    """AC-5: user message PII is redacted before the orchestrator LLM sees it.

    The ``redact_inbound`` node must run before the orchestrator node.
    The prompt passed to the orchestrator's ``_structured_llm.ainvoke``
    must not contain the original email address.
    """
    from second_brain.graphs.query_graph import build_query_graph

    mem_saver = _make_mem_saver()
    captured_prompts: list[str] = []

    async def capturing_orch_ainvoke(prompt: str, **_kwargs) -> MagicMock:
        captured_prompts.append(prompt)
        return _mock_routing("neither")

    with (
        patch(
            "second_brain.graphs.query_graph.AsyncConnectionPool",
            MagicMock(return_value=AsyncMock()),
        ),
        patch(
            "second_brain.graphs.query_graph.AsyncPostgresSaver",
            _mock_saver_factory(mem_saver),
        ),
        patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm,
        patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm,
    ):
        mock_orch_llm.ainvoke = AsyncMock(side_effect=capturing_orch_ainvoke)
        mock_synth_llm.ainvoke = AsyncMock(
            return_value=_mock_synthesis("Here is your answer.")
        )

        graph, _pool = await build_query_graph(
            "postgresql://fake:test@localhost:5432/test"
        )

        pii_message = "My email is alice.wonderland@example.com and I need help."
        result = await graph.ainvoke(
            _base_input_state(pii_message, session_id="ac5-session"),
            config={"configurable": {"thread_id": "ac5-session"}},
        )

    # The orchestrator must have been called exactly once
    assert len(captured_prompts) == 1, (
        f"Expected orchestrator to be called once; got {len(captured_prompts)}"
    )

    prompt_text = captured_prompts[0]

    # Raw email must NOT appear in the prompt the LLM sees
    assert "alice.wonderland@example.com" not in prompt_text, (
        "Raw email leaked to orchestrator LLM — redact_inbound did not run first"
    )

    # Redacted token must be present (Presidio replaces EMAIL_ADDRESS with [EMAIL])
    assert "[EMAIL]" in prompt_text, (
        f"Expected '[EMAIL]' placeholder in orchestrator prompt; got:\n{prompt_text}"
    )

    # The graph must still produce a final_answer
    assert result["final_answer"] != "", "Graph must produce a non-empty final_answer"


# ---------------------------------------------------------------------------
# AC-6: PII is redacted outbound (final_answer never exposes raw PII)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ac6_pii_redacted_in_final_answer():
    """AC-6: PII that the LLM injects into its answer is stripped before returning.

    The ``redact_outbound`` node must scrub the synthesis output so the
    caller never sees raw personal data in ``final_answer``.
    """
    from second_brain.graphs.query_graph import build_query_graph

    mem_saver = _make_mem_saver()

    # LLM returns an answer that contains PII
    pii_answer = (
        "The contact person is John Doe and you can reach them at "
        "john.doe@secretcorp.com for further assistance."
    )

    with (
        patch(
            "second_brain.graphs.query_graph.AsyncConnectionPool",
            MagicMock(return_value=AsyncMock()),
        ),
        patch(
            "second_brain.graphs.query_graph.AsyncPostgresSaver",
            _mock_saver_factory(mem_saver),
        ),
        patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm,
        patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm,
    ):
        mock_orch_llm.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
        mock_synth_llm.ainvoke = AsyncMock(return_value=_mock_synthesis(pii_answer))

        graph, _pool = await build_query_graph(
            "postgresql://fake:test@localhost:5432/test"
        )

        result = await graph.ainvoke(
            _base_input_state("Who should I contact?", session_id="ac6-session"),
            config={"configurable": {"thread_id": "ac6-session"}},
        )

    final = result["final_answer"]

    # Raw name and email must be redacted
    assert "John Doe" not in final, (
        f"Person name leaked into final_answer — redact_outbound did not scrub it.\n"
        f"final_answer={final!r}"
    )
    assert "john.doe@secretcorp.com" not in final, (
        f"Email leaked into final_answer — redact_outbound did not scrub it.\n"
        f"final_answer={final!r}"
    )

    # Presidio replacement tokens must be present
    assert "[NAME]" in final or "[EMAIL]" in final, (
        f"Expected redaction placeholders in final_answer; got:\n{final!r}"
    )


# ---------------------------------------------------------------------------
# AC-10: null session_id creates a new UUID; same session_id continues thread
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ac10_null_session_id_creates_new_thread_uuid_continues():
    """AC-10: omitting sessionId generates a fresh UUID; supplying the returned
    sessionId on the next call re-uses the same LangGraph thread (same thread_id
    passed to ainvoke), providing session continuity.

    Also covers the fix for retrievedContexts fidelity: with routing_decision
    "neither" and no memory hits, the /query response's retrievedContexts must
    be []. memory_retrieval_node runs on an unconditional graph edge regardless
    of routing_decision and would otherwise call the real embed_text()/
    get_pgvector_pool() (live Postgres/Ollama), so it is stubbed out here; the
    memory_agent's LLM is likewise stubbed since memory_agent_node always runs
    after synthesis.
    """
    import uuid

    from httpx import ASGITransport, AsyncClient

    import second_brain.api.routers.query as query_module
    from second_brain.graphs.query_graph import build_query_graph
    from second_brain.main import app

    mem_saver = _make_mem_saver()
    thread_ids_seen: list[str] = []

    async def recording_ainvoke(state: dict, *, config: dict, **_kwargs) -> dict:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        thread_ids_seen.append(thread_id)
        return {
            **state,
            "final_answer": "Second Brain is here to help.",
            "confidence": 0.9,
            "is_uncertain": False,
            "conflict_context": [],
        }

    # memory_retrieval_node runs unconditionally before the orchestrator; stub it
    # so the graph never touches real embeddings/pgvector during this test.
    async def _stub_memory_retrieval_node(_state: dict) -> dict:
        return {"retrieved_memory": []}

    mock_memory_agent_output = MagicMock()
    mock_memory_agent_output.fact_updates = []
    mock_memory_agent_output.correction_updates = []

    with (
        patch(
            "second_brain.graphs.query_graph.AsyncConnectionPool",
            MagicMock(return_value=AsyncMock()),
        ),
        patch(
            "second_brain.graphs.query_graph.AsyncPostgresSaver",
            _mock_saver_factory(mem_saver),
        ),
        patch(
            "second_brain.graphs.query_graph.memory_retrieval_node",
            _stub_memory_retrieval_node,
        ),
        patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm,
        patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm,
    ):
        mock_orch_llm.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
        mock_synth_llm.ainvoke = AsyncMock(
            return_value=_mock_synthesis("Second Brain is here to help.")
        )

        real_graph, _pool = await build_query_graph(
            "postgresql://fake:test@localhost:5432/test"
        )

    # Wrap ainvoke so we can record the thread_id without re-entering mock blocks
    original_ainvoke = real_graph.ainvoke

    async def wrapped_ainvoke(state, **kwargs):
        config = kwargs.get("config", {})
        thread_id = config.get("configurable", {}).get("thread_id", "")
        thread_ids_seen.append(thread_id)
        return await original_ainvoke(state, **kwargs)

    real_graph.ainvoke = wrapped_ainvoke  # type: ignore[method-assign]

    # Patch the router so it uses our pre-built graph (skipping real Postgres init)
    original_graph_attr = query_module._graph
    original_pool_attr = query_module._pool

    async def fake_build_query_graph(_url: str):
        return real_graph, None

    try:
        query_module._graph = None  # force _get_graph to call build_query_graph
        query_module._pool = None

        with (
            patch(
                "second_brain.api.routers.query.build_query_graph",
                fake_build_query_graph,
            ),
            patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch2,
            patch("second_brain.nodes.synthesis._structured_llm") as mock_synth2,
            patch("second_brain.nodes.memory_agent._llm") as mock_memory_agent_llm,
        ):
            mock_orch2.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
            mock_synth2.ainvoke = AsyncMock(
                return_value=_mock_synthesis("Second Brain is here to help.")
            )
            mock_memory_agent_llm.ainvoke = AsyncMock(
                return_value=mock_memory_agent_output
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # --- First call: no sessionId ---
                resp1 = await client.post("/query", json={"message": "Hello!"})
                assert resp1.status_code == 200, f"First call failed: {resp1.text}"
                data1 = resp1.json()

                session_id = data1["sessionId"]
                assert session_id, "First response must contain a non-empty sessionId"

                # sessionId must be a valid UUID (36-char hyphenated string)
                parsed = uuid.UUID(session_id)
                assert str(parsed) == session_id, (
                    f"sessionId must be a valid UUID; got {session_id!r}"
                )

                # routing_decision="neither" and no memory hits -> no grounding
                # context was used, so retrievedContexts must be empty.
                assert data1["retrievedContexts"] == []

                # --- Second call: supply the returned sessionId ---
                resp2 = await client.post(
                    "/query",
                    json={"message": "What did I say?", "sessionId": session_id},
                )
                assert resp2.status_code == 200, f"Second call failed: {resp2.text}"
                data2 = resp2.json()

                # Same session must be returned
                assert data2["sessionId"] == session_id, (
                    f"Second call must echo back the same sessionId; "
                    f"got {data2['sessionId']!r}"
                )
                assert data2["retrievedContexts"] == []

    finally:
        # Restore router state to avoid cross-test pollution
        query_module._graph = original_graph_attr
        query_module._pool = original_pool_attr

    # Both calls must have used the same thread_id (session continuity)
    assert len(thread_ids_seen) >= 2, (
        f"Expected at least 2 ainvoke calls (one per request); got {thread_ids_seen}"
    )
    assert thread_ids_seen[-2] == thread_ids_seen[-1] == session_id, (
        f"Both graph invocations must use thread_id={session_id!r}; "
        f"recorded thread_ids={thread_ids_seen}"
    )
