from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from second_brain.graphs.state import MemoryItem, SecondBrainState
from second_brain.nodes.memory_retrieval import memory_retrieval_node


def _make_state(**overrides) -> SecondBrainState:
    base: SecondBrainState = {
        "session_id": "test-session",
        "messages": [HumanMessage(content="What food do I like?")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.8,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


def _make_mock_pool(fact_rows, correction_rows):
    """Build a mock asyncpg Pool whose acquire() returns a conn with fetch()."""
    mock_conn = AsyncMock()
    # First fetch call = learned_facts, second = model_corrections
    mock_conn.fetch = AsyncMock(side_effect=[fact_rows, correction_rows])

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


@pytest.mark.asyncio
async def test_merges_and_sorts_by_score():
    """Merges learned_facts + model_corrections, sorted descending by score."""
    fact_row = {
        "id": "fact-1",
        "fact": "The user likes sushi",
        "confidence": 0.9,
        "score": 0.92,
    }
    corr_row = {"id": "corr-1", "fact": "Tokyo is in Japan", "score": 0.85}

    mock_pool = _make_mock_pool([fact_row], [corr_row])
    mock_embedding = [0.1] * 1024

    with (
        patch(
            "second_brain.nodes.memory_retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=mock_embedding,
        ),
        patch(
            "second_brain.nodes.memory_retrieval.get_pgvector_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        result = await memory_retrieval_node(_make_state())

    memory: list[MemoryItem] = result["retrieved_memory"]
    assert len(memory) == 2
    assert memory[0]["id"] == "fact-1"
    assert memory[0]["type"] == "learned_fact"
    assert memory[0]["confidence"] == 0.9
    assert memory[1]["id"] == "corr-1"
    assert memory[1]["type"] == "model_correction"
    assert memory[1]["confidence"] == 1.0


@pytest.mark.asyncio
async def test_returns_empty_when_db_empty():
    """Returns empty retrieved_memory when no rows exist."""
    mock_pool = _make_mock_pool([], [])

    with (
        patch(
            "second_brain.nodes.memory_retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=[0.0] * 1024,
        ),
        patch(
            "second_brain.nodes.memory_retrieval.get_pgvector_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        result = await memory_retrieval_node(_make_state())

    assert result["retrieved_memory"] == []


@pytest.mark.asyncio
async def test_uses_last_human_message_by_type():
    """embed_text called with last HumanMessage content (found by type, not index)."""
    state = _make_state(
        messages=[
            HumanMessage(content="First"),
            AIMessage(content="Reply"),
            HumanMessage(content="Second — this one"),
        ]
    )
    mock_pool = _make_mock_pool([], [])

    with (
        patch(
            "second_brain.nodes.memory_retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 1024,
        ) as mock_embed,
        patch(
            "second_brain.nodes.memory_retrieval.get_pgvector_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        await memory_retrieval_node(state)

    mock_embed.assert_called_once_with("Second — this one")


@pytest.mark.asyncio
async def test_fails_hard_when_embed_raises():
    """Ollama unavailability propagates as an exception — no empty-list fallback."""
    with patch(
        "second_brain.nodes.memory_retrieval.embed_text",
        side_effect=ValueError("Ollama down"),
    ):
        with pytest.raises(ValueError, match="Ollama down"):
            await memory_retrieval_node(_make_state())


@pytest.mark.asyncio
async def test_threshold_applied_to_sql_queries():
    """Both _search_facts and _search_corrections pass threshold in WHERE clause."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(side_effect=[[], []])

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "second_brain.nodes.memory_retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 1024,
        ),
        patch(
            "second_brain.nodes.memory_retrieval.get_pgvector_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        await memory_retrieval_node(_make_state())

    calls = mock_conn.fetch.call_args_list
    assert len(calls) == 2, f"Expected 2 fetch calls, got {len(calls)}"

    for i, call in enumerate(calls):
        sql = call.args[0]
        assert "WHERE" in sql, f"Call {i}: SQL missing WHERE threshold clause: {sql}"
        assert len(call.args) >= 3, (
            f"Call {i}: threshold not passed as 3rd argument: {call.args}"
        )
        assert call.args[2] == pytest.approx(0.5), (
            f"Call {i}: expected threshold 0.5, got {call.args[2]}"
        )


@pytest.mark.asyncio
async def test_threshold_excludes_low_similarity_corrections():
    """Corrections below threshold are excluded by the WHERE clause.

    DB returns empty because WHERE filtered out low-similarity rows.
    """
    mock_pool = _make_mock_pool([], [])

    with (
        patch(
            "second_brain.nodes.memory_retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 1024,
        ),
        patch(
            "second_brain.nodes.memory_retrieval.get_pgvector_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        result = await memory_retrieval_node(_make_state())

    assert result["retrieved_memory"] == []


@pytest.mark.asyncio
async def test_threshold_allows_high_similarity_results():
    """Facts and corrections above threshold are still returned."""
    fact_row = {
        "id": "fact-hi",
        "fact": "User loves Python",
        "confidence": 0.95,
        "score": 0.85,
    }
    corr_row = {"id": "corr-hi", "fact": "Python is a language", "score": 0.72}

    mock_pool = _make_mock_pool([fact_row], [corr_row])

    with (
        patch(
            "second_brain.nodes.memory_retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 1024,
        ),
        patch(
            "second_brain.nodes.memory_retrieval.get_pgvector_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
    ):
        result = await memory_retrieval_node(_make_state())

    memory = result["retrieved_memory"]
    assert len(memory) == 2
    ids = {m["id"] for m in memory}
    assert ids == {"fact-hi", "corr-hi"}
