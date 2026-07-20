from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.nodes.rag_retrieval import retrieve_from_rag
from tests.unit.conftest import make_state


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
        patch(
            "second_brain.nodes.rag_retrieval.embed_text", side_effect=capture_embed
        ),
        patch(
            "second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock
        ) as mock_db,
    ):
        mock_db.return_value = []
        await retrieve_from_rag(state)

    assert captured_queries == ["Tell me about Python."]
