"""Unit tests for web_research node."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from tests.unit.conftest import make_state

TAVILY_PATCH = "second_brain.nodes.web_research.TavilyClient"


@pytest.mark.asyncio
async def test_search_web_returns_web_results():
  """Happy path: search_web returns mapped WebResult list from Tavily response."""
  mock_response = {
    "results": [
      {
        "title": "Result 1",
        "url": "https://example.com/1",
        "content": "Content 1",
      },
      {
        "title": "Result 2",
        "url": "https://example.com/2",
        "content": "Content 2",
      },
      {
        "title": "Result 3",
        "url": "https://example.com/3",
        "content": "Content 3",
      },
    ]
  }
  mock_client = MagicMock()
  mock_client.search.return_value = mock_response

  state = make_state(messages=[HumanMessage(content="What is quantum computing?")])

  with patch(TAVILY_PATCH, return_value=mock_client):
    from second_brain.nodes.web_research import search_web

    result = await search_web(state)

  assert "web_results" in result
  assert len(result["web_results"]) == 3
  assert result["web_results"][0]["title"] == "Result 1"
  assert result["web_results"][0]["url"] == "https://example.com/1"
  assert result["web_results"][0]["content"] == "Content 1"


@pytest.mark.asyncio
async def test_search_web_returns_empty_results_when_no_results():
  """Edge case: Tavily returns empty results — node returns empty web_results."""
  mock_client = MagicMock()
  mock_client.search.return_value = {"results": []}

  state = make_state(messages=[HumanMessage(content="obscure query with no results")])

  with patch(TAVILY_PATCH, return_value=mock_client):
    from second_brain.nodes.web_research import search_web

    result = await search_web(state)

  assert result["web_results"] == []


@pytest.mark.asyncio
async def test_search_web_uses_last_message_as_query():
  """Correct query: last message content is passed to Tavily client search."""
  mock_client = MagicMock()
  mock_client.search.return_value = {"results": []}

  query_text = "What are the best Python testing frameworks?"
  state = make_state(
    messages=[
      HumanMessage(content="previous message"),
      HumanMessage(content=query_text),
    ]
  )

  with patch(TAVILY_PATCH, return_value=mock_client):
    from second_brain.nodes.web_research import search_web

    await search_web(state)

  mock_client.search.assert_called_once_with(query_text, max_results=3)
