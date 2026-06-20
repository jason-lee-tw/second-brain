"""Unit tests for the RAG retrieval node."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

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
