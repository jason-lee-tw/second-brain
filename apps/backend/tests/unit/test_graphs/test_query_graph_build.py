# apps/backend/tests/unit/test_graphs/test_query_graph_build.py
"""Tests for the SecondBrain query LangGraph builder."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from second_brain.graphs.state import SecondBrainState

# ---------------------------------------------------------------------------
# _route_retrieval unit tests (pure function, no mocking needed)
# ---------------------------------------------------------------------------


def test_route_retrieval_both_returns_send_to_rag_and_web():
    """routing_decision='both' must fan-out to both rag_retrieval and web_research."""
    from langgraph.types import Send

    from second_brain.graphs.query_graph import _route_retrieval

    state: SecondBrainState = {
        "session_id": "s1",
        "messages": [],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "both",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    result = _route_retrieval(state)
    assert isinstance(result, list)
    assert len(result) == 2
    nodes = {s.node for s in result}
    assert nodes == {"rag_retrieval", "web_research"}
    for s in result:
        assert isinstance(s, Send)


def test_route_retrieval_rag_only():
    """routing_decision='rag' must fan-out to rag_retrieval only."""
    from langgraph.types import Send

    from second_brain.graphs.query_graph import _route_retrieval

    state: SecondBrainState = {
        "session_id": "s1",
        "messages": [],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "rag",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    result = _route_retrieval(state)
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], Send)
    assert result[0].node == "rag_retrieval"


def test_route_retrieval_web_only():
    """routing_decision='web' must fan-out to web_research only."""
    from langgraph.types import Send

    from second_brain.graphs.query_graph import _route_retrieval

    state: SecondBrainState = {
        "session_id": "s1",
        "messages": [],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "web",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    result = _route_retrieval(state)
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], Send)
    assert result[0].node == "web_research"


def test_route_retrieval_neither_returns_synthesis_string():
    """routing_decision='neither' must return the string 'synthesis' (no retrieval)."""
    from second_brain.graphs.query_graph import _route_retrieval

    state: SecondBrainState = {
        "session_id": "s1",
        "messages": [],
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
    result = _route_retrieval(state)
    assert result == "synthesis"


# ---------------------------------------------------------------------------
# build_query_graph integration tests (mocked checkpointer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_query_graph_returns_compiled_graph():
    """build_query_graph must return a compiled graph with ainvoke."""
    mock_pool = AsyncMock()
    mock_pool_class = MagicMock(return_value=mock_pool)
    mock_saver = MagicMock()
    mock_saver.setup = AsyncMock()

    with (
        patch("second_brain.graphs.query_graph.AsyncConnectionPool", mock_pool_class),
        patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
    ):
        MockSaver.return_value = mock_saver
        from second_brain.graphs.query_graph import build_query_graph

        graph, pool = await build_query_graph(
            "postgresql://fake:fake@localhost:5432/test"
        )

    assert hasattr(graph, "ainvoke")


@pytest.mark.asyncio
async def test_build_query_graph_calls_pool_open():
    """build_query_graph must call pool.open() to establish connections."""
    mock_pool = AsyncMock()
    mock_pool_class = MagicMock(return_value=mock_pool)
    mock_saver = MagicMock()
    mock_saver.setup = AsyncMock()

    with (
        patch("second_brain.graphs.query_graph.AsyncConnectionPool", mock_pool_class),
        patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
    ):
        MockSaver.return_value = mock_saver
        from second_brain.graphs.query_graph import build_query_graph

        await build_query_graph("postgresql://fake:fake@localhost:5432/test")

    mock_pool.open.assert_called_once()


@pytest.mark.asyncio
async def test_build_query_graph_calls_checkpointer_setup():
    """build_query_graph must call checkpointer.setup() to init postgres tables."""
    mock_pool = AsyncMock()
    mock_pool_class = MagicMock(return_value=mock_pool)
    mock_saver = MagicMock()
    mock_saver.setup = AsyncMock()

    with (
        patch("second_brain.graphs.query_graph.AsyncConnectionPool", mock_pool_class),
        patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
    ):
        MockSaver.return_value = mock_saver
        from second_brain.graphs.query_graph import build_query_graph

        await build_query_graph("postgresql://fake:fake@localhost:5432/test")

    mock_saver.setup.assert_called_once()


@pytest.mark.asyncio
async def test_build_query_graph_closes_pool_on_checkpointer_setup_failure():
    """build_query_graph must close the pool if checkpointer.setup() raises."""
    mock_pool = AsyncMock()
    mock_pool_class = MagicMock(return_value=mock_pool)
    mock_saver = MagicMock()
    mock_saver.setup = AsyncMock(side_effect=RuntimeError("setup failed"))

    with (
        patch("second_brain.graphs.query_graph.AsyncConnectionPool", mock_pool_class),
        patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
    ):
        MockSaver.return_value = mock_saver
        from second_brain.graphs.query_graph import build_query_graph

        with pytest.raises(RuntimeError, match="setup failed"):
            await build_query_graph("postgresql://fake:fake@localhost:5432/test")

    mock_pool.close.assert_called_once()
