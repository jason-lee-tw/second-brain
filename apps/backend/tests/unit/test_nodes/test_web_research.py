from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.nodes.web_research import search_web
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_returns_web_results():
    state = make_state(messages=[HumanMessage(content="What is new in Python 4?")])

    with (
        patch(
            "second_brain.nodes.web_research.tavily_search",
            new_callable=AsyncMock,
        ) as mock_search,
        patch(
            "second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock
        ),
    ):
        mock_search.return_value = [
            {
                "title": "Python 4 Released",
                "url": "https://python.org/news",
                "content": "Python 4 adds new features...",
            },
            {
                "title": "PEP 999",
                "url": "https://peps.python.org/pep-0999",
                "content": "PEP 999 proposes...",
            },
        ]

        result = await search_web(state)

    assert "web_results" in result
    assert len(result["web_results"]) == 2
    assert result["web_results"][0]["title"] == "Python 4 Released"
    assert result["web_results"][0]["url"] == "https://python.org/news"
    assert "Python 4 adds" in result["web_results"][0]["content"]


@pytest.mark.asyncio
async def test_rate_limit_sleep_called():
    """Verify asyncio.sleep(1) is called for rate limiting — max 1 call/second."""
    state = make_state(messages=[HumanMessage(content="Latest AI news?")])

    with (
        patch(
            "second_brain.nodes.web_research.tavily_search",
            new_callable=AsyncMock,
        ) as mock_search,
        patch(
            "second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_search.return_value = []

        await search_web(state)

    mock_sleep.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    state = make_state(messages=[HumanMessage(content="Something very obscure??")])

    with (
        patch(
            "second_brain.nodes.web_research.tavily_search",
            new_callable=AsyncMock,
        ) as mock_search,
        patch(
            "second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock
        ),
    ):
        mock_search.return_value = []

        result = await search_web(state)

    assert result["web_results"] == []


@pytest.mark.asyncio
async def test_searches_with_last_message_content_and_max_results_three():
    """Verify the query passed to Tavily is messages[-1].content, max_results=3."""
    state = make_state(messages=[HumanMessage(content="Rust 2025 edition features?")])

    with (
        patch(
            "second_brain.nodes.web_research.tavily_search",
            new_callable=AsyncMock,
        ) as mock_search,
        patch(
            "second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock
        ),
    ):
        mock_search.return_value = []

        await search_web(state)

    mock_search.assert_called_once_with(
        "Rust 2025 edition features?", max_results=3
    )
