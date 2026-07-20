from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

import second_brain.nodes.rag_retrieval as rag_retrieval
from second_brain.nodes.rag_retrieval import (
    _get_pool,
    _query_pgvector,
    retrieve_from_rag,
)
from tests.unit.conftest import make_state


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    """The module-level `_pool` is a lazy singleton — reset it around every
    test so pool-creation assertions don't leak across tests."""
    rag_retrieval._pool = None
    yield
    rag_retrieval._pool = None


@pytest.mark.asyncio
async def test_returns_rag_results_list():
    state = make_state(messages=[HumanMessage(content="What is LangGraph?")])

    fake_rows = [
        {
            "content": "LangGraph is a library for building stateful agents.",
            "score": 0.92,
            "chunk_index": 0,
            "metadata": {"source": "langchain.md"},
        },
        {
            "content": "LangGraph uses StateGraph to manage state.",
            "score": 0.88,
            "chunk_index": 1,
            "metadata": {"source": "langchain.md"},
        },
    ]

    with (
        patch(
            "second_brain.nodes.rag_retrieval.embed_text", new_callable=AsyncMock
        ) as mock_embed,
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock
        ) as mock_db,
    ):
        mock_embed.return_value = [0.1] * 1024
        mock_db.return_value = fake_rows

        result = await retrieve_from_rag(state)

    assert "rag_results" in result
    assert len(result["rag_results"]) == 2
    assert result["rag_results"][0]["score"] == 0.92
    assert result["rag_results"][0]["chunk_index"] == 0
    assert (
        result["rag_results"][0]["content"]
        == "LangGraph is a library for building stateful agents."
    )


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    state = make_state(messages=[HumanMessage(content="What is the meaning of life?")])

    with (
        patch(
            "second_brain.nodes.rag_retrieval.embed_text", new_callable=AsyncMock
        ) as mock_embed,
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock
        ) as mock_db,
    ):
        mock_embed.return_value = [0.0] * 1024
        mock_db.return_value = []

        result = await retrieve_from_rag(state)

    assert result["rag_results"] == []


@pytest.mark.asyncio
async def test_embeds_last_message_content():
    """Verify the query used for embedding is messages[-1].content."""
    state = make_state(messages=[HumanMessage(content="Tell me about Python.")])
    captured_queries = []

    async def capture_embed(query):
        captured_queries.append(query)
        return [0.1] * 1024

    with (
        patch("second_brain.nodes.rag_retrieval.embed_text", side_effect=capture_embed),
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock
        ) as mock_db,
    ):
        mock_db.return_value = []
        await retrieve_from_rag(state)

    assert captured_queries == ["Tell me about Python."]


@pytest.mark.asyncio
async def test_get_pool_creates_pool_once_via_create_pool_with_init_callback():
    """_get_pool must lazily create a single asyncpg.Pool, registering the
    pgvector codec via the pool's `init` callback rather than per-call connect."""
    fake_pool = MagicMock()

    with patch(
        "second_brain.nodes.rag_retrieval.asyncpg.create_pool", new_callable=AsyncMock
    ) as mock_create_pool:
        mock_create_pool.return_value = fake_pool

        pool_first = await _get_pool("postgresql://test")
        pool_second = await _get_pool("postgresql://test")

    assert pool_first is fake_pool
    assert pool_second is fake_pool
    mock_create_pool.assert_awaited_once_with(
        "postgresql://test", init=rag_retrieval.register_vector
    )


@pytest.mark.asyncio
async def test_query_pgvector_acquires_connection_from_pool():
    """_query_pgvector must fetch rows via a connection acquired from the
    shared pool, not a fresh asyncpg.connect() per call."""
    fake_row = {
        "content": "some chunk",
        "score": 0.5,
        "chunk_index": 0,
        "metadata": {},
    }
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [fake_row]

    mock_acquire_cm = AsyncMock()
    mock_acquire_cm.__aenter__.return_value = mock_conn
    mock_acquire_cm.__aexit__.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_cm

    with patch(
        "second_brain.nodes.rag_retrieval._get_pool", new_callable=AsyncMock
    ) as mock_get_pool:
        mock_get_pool.return_value = mock_pool

        results = await _query_pgvector([0.1] * 1024, "postgresql://test")

    assert len(results) == 1
    assert results[0]["content"] == "some chunk"
    mock_pool.acquire.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_closes_pool_when_created():
    fake_pool = AsyncMock()
    rag_retrieval._pool = fake_pool

    await rag_retrieval.shutdown()

    fake_pool.close.assert_awaited_once()
    assert rag_retrieval._pool is None


@pytest.mark.asyncio
async def test_shutdown_is_noop_when_no_pool_created():
    assert rag_retrieval._pool is None

    await rag_retrieval.shutdown()  # should not raise

    assert rag_retrieval._pool is None
