"""Unit tests for the RAG retrieval node."""

import json as _json  # alias used in JSONB codec tests
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.nodes import rag_retrieval
from tests.unit.conftest import make_state

MOCK_EMBEDDING = [0.1, 0.2, 0.3]
MOCK_ROWS = [
    {
        "content": "Python is a programming language.",
        "score": 0.95,
        "chunk_index": 0,
        "metadata": {"source": "python_intro.md"},
    },
    {
        "content": "LangGraph is a library for building stateful agents.",
        "score": 0.88,
        "chunk_index": 1,
        "metadata": {"source": "langgraph_docs.md"},
    },
]


@pytest.mark.asyncio
async def test_retrieve_from_rag_happy_path():
    """Happy path: returns rag_results populated from pgvector rows."""
    state = make_state(messages=[HumanMessage(content="What is Python?")])

    with (
        patch(
            "second_brain.nodes.rag_retrieval._embed_query",
            new=AsyncMock(return_value=MOCK_EMBEDDING),
        ) as mock_embed,
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector",
            new=AsyncMock(return_value=MOCK_ROWS),
        ) as mock_query,
    ):
        from second_brain.nodes.rag_retrieval import retrieve_from_rag

        result = await retrieve_from_rag(state)

    mock_embed.assert_awaited_once()
    mock_query.assert_awaited_once()
    assert "rag_results" in result
    assert len(result["rag_results"]) == 2
    assert result["rag_results"][0]["content"] == "Python is a programming language."
    assert result["rag_results"][0]["score"] == 0.95
    assert result["rag_results"][0]["chunk_index"] == 0
    assert result["rag_results"][0]["metadata"] == {"source": "python_intro.md"}


@pytest.mark.asyncio
async def test_retrieve_from_rag_empty_results():
    """Edge case: pgvector returns no rows — rag_results is an empty list."""
    state = make_state(messages=[HumanMessage(content="Unknown topic")])

    with (
        patch(
            "second_brain.nodes.rag_retrieval._embed_query",
            new=AsyncMock(return_value=MOCK_EMBEDDING),
        ),
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector",
            new=AsyncMock(return_value=[]),
        ),
    ):
        from second_brain.nodes.rag_retrieval import retrieve_from_rag

        result = await retrieve_from_rag(state)

    assert result["rag_results"] == []


@pytest.mark.asyncio
async def test_retrieve_from_rag_uses_last_message():
    """Edge case: query uses the last message content from state messages list."""
    messages = [
        HumanMessage(content="First message"),
        HumanMessage(content="What is LangGraph?"),
    ]
    state = make_state(messages=messages)

    captured_query = []

    async def fake_embed(query: str, base_url: str) -> list[float]:
        captured_query.append(query)
        return MOCK_EMBEDDING

    with (
        patch(
            "second_brain.nodes.rag_retrieval._embed_query",
            new=fake_embed,
        ),
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector",
            new=AsyncMock(return_value=MOCK_ROWS),
        ),
    ):
        from second_brain.nodes.rag_retrieval import retrieve_from_rag

        await retrieve_from_rag(state)

    assert captured_query == ["What is LangGraph?"]


# ---------------------------------------------------------------------------
# Pool singleton tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_rag_pool_creates_pool_once():
    """Pool singleton: asyncpg.create_pool is called exactly once on repeated calls."""
    from second_brain.nodes.rag_retrieval import _get_rag_pool

    # Reset singleton so the test is isolated
    rag_retrieval._rag_pool = None

    mock_pool = AsyncMock()

    with patch(
        "second_brain.nodes.rag_retrieval.asyncpg.create_pool",
        new=AsyncMock(return_value=mock_pool),
    ) as mock_create:
        pool1 = await _get_rag_pool("postgresql://test/db")
        pool2 = await _get_rag_pool("postgresql://test/db")

    mock_create.assert_awaited_once()
    assert pool1 is pool2

    # Clean up module-level state
    rag_retrieval._rag_pool = None


@pytest.mark.asyncio
async def test_shutdown_rag_pool_closes_and_resets():
    """shutdown_rag_pool closes the pool and resets the singleton to None."""
    from second_brain.nodes.rag_retrieval import shutdown_rag_pool

    mock_pool = AsyncMock()
    rag_retrieval._rag_pool = mock_pool

    await shutdown_rag_pool()

    mock_pool.close.assert_awaited_once()
    assert rag_retrieval._rag_pool is None


@pytest.mark.asyncio
async def test_setup_conn_registers_vector_and_jsonb_codec():
    """_setup_conn must call register_vector AND set_type_codec for jsonb."""
    from second_brain.nodes.rag_retrieval import _setup_conn

    mock_conn = AsyncMock()
    mock_conn.set_type_codec = AsyncMock()

    with patch(
        "second_brain.nodes.rag_retrieval.register_vector",
        new=AsyncMock(),
    ) as mock_rv:
        await _setup_conn(mock_conn)

    mock_rv.assert_awaited_once_with(mock_conn)
    mock_conn.set_type_codec.assert_awaited_once_with(
        "jsonb",
        encoder=_json.dumps,
        decoder=_json.loads,
        schema="pg_catalog",
    )


@pytest.mark.asyncio
async def test_get_rag_pool_passes_setup_conn_as_init():
    """asyncpg.create_pool must receive init=_setup_conn for JSONB auto-decoding."""
    from second_brain.nodes.rag_retrieval import _get_rag_pool, _setup_conn

    rag_retrieval._rag_pool = None
    mock_pool = AsyncMock()

    with patch(
        "second_brain.nodes.rag_retrieval.asyncpg.create_pool",
        new=AsyncMock(return_value=mock_pool),
    ) as mock_create:
        await _get_rag_pool("postgresql://test/db")

    mock_create.assert_awaited_once_with("postgresql://test/db", init=_setup_conn)

    # Clean up module-level state
    rag_retrieval._rag_pool = None


@pytest.mark.asyncio
async def test_query_pgvector_uses_pool_acquire():
    """_query_pgvector uses pool.acquire() and never calls asyncpg.connect directly."""
    from second_brain.nodes.rag_retrieval import _query_pgvector

    mock_rows = [
        MagicMock(
            **{
                "__getitem__.side_effect": lambda key: {
                    "content": "Test content",
                    "score": 0.9,
                    "chunk_index": 0,
                    "metadata": {
                        "source": "test.md",
                        "heading_path": "",
                        "content_type": "article",
                        "char_count": 100,
                    },
                }[key]
            }
        )
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    mock_pool = MagicMock()

    @asynccontextmanager
    async def fake_acquire():
        yield mock_conn

    mock_pool.acquire = fake_acquire

    with (
        patch(
            "second_brain.nodes.rag_retrieval._get_rag_pool",
            new=AsyncMock(return_value=mock_pool),
        ) as mock_get_pool,
        patch(
            "second_brain.nodes.rag_retrieval.asyncpg.connect",
        ) as mock_connect,
    ):
        result = await _query_pgvector([0.1, 0.2, 0.3], "postgresql://test/db")

    mock_get_pool.assert_awaited_once()
    mock_connect.assert_not_called()
    assert len(result) == 1
    assert result[0]["content"] == "Test content"
    assert result[0]["score"] == 0.9


# ---------------------------------------------------------------------------
# _row_to_chunk_metadata helper tests
# ---------------------------------------------------------------------------


def test_row_to_chunk_metadata_happy_path():
    from second_brain.nodes.rag_retrieval import _row_to_chunk_metadata

    result = _row_to_chunk_metadata(
        {
            "source": "docs/foo.md",
            "heading_path": "Intro > Setup",
            "content_type": "article",
            "char_count": 42,
        }
    )
    assert result["source"] == "docs/foo.md"
    assert result["heading_path"] == "Intro > Setup"
    assert result["content_type"] == "article"
    assert result["char_count"] == 42


def test_row_to_chunk_metadata_missing_field():
    from second_brain.nodes.rag_retrieval import _row_to_chunk_metadata

    with pytest.raises(KeyError):
        _row_to_chunk_metadata(
            {"source": "x.md", "heading_path": "", "content_type": "article"}
        )


def test_row_to_chunk_metadata_char_count_none():
    from second_brain.nodes.rag_retrieval import _row_to_chunk_metadata

    with pytest.raises(TypeError):
        _row_to_chunk_metadata(
            {
                "source": "x.md",
                "heading_path": "",
                "content_type": "note",
                "char_count": None,
            }
        )
