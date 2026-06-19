# apps/backend/tests/unit/test_services/test_tavily.py
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_crawl_url_returns_raw_content():
    """crawl_url must return the raw_content string from Tavily extract."""
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(
        return_value={
            "results": [{"raw_content": "# Scraped Page\n\nBody text here."}]
        }
    )

    with patch(
        "second_brain.services.tavily.AsyncTavilyClient",
        return_value=mock_client,
    ):
        from second_brain.services.tavily import crawl_url

        result = await crawl_url("https://example.com/article")

    assert result == "# Scraped Page\n\nBody text here."


@pytest.mark.asyncio
async def test_crawl_url_raises_when_no_results():
    """crawl_url must raise ValueError when Tavily returns empty results."""
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value={"results": []})

    with patch(
        "second_brain.services.tavily.AsyncTavilyClient",
        return_value=mock_client,
    ):
        from second_brain.services.tavily import crawl_url

        with pytest.raises(ValueError, match="no content"):
            await crawl_url("https://example.com/empty")


@pytest.mark.asyncio
async def test_crawl_and_save_writes_markdown_file(tmp_path):
    """crawl_and_save must save crawled content as a .md file and return its path."""
    pending_dir = tmp_path / "pending-digest-docs"
    pending_dir.mkdir()

    with patch("second_brain.services.tavily.AsyncTavilyClient") as mock_cls, patch(
        "second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir
    ):
        mock_client = AsyncMock()
        mock_client.extract = AsyncMock(
            return_value={"results": [{"raw_content": "# Hello\n\nWorld."}]}
        )
        mock_cls.return_value = mock_client

        from second_brain.services.tavily import crawl_and_save

        saved_path = await crawl_and_save("https://example.com/page")

    assert saved_path.exists()
    assert saved_path.suffix == ".md"
    assert saved_path.read_text() == "# Hello\n\nWorld."


@pytest.mark.asyncio
async def test_crawl_and_save_slugifies_url_to_filename(tmp_path):
    """crawl_and_save filename must be derived from the URL, not random."""
    pending_dir = tmp_path / "pending-digest-docs"
    pending_dir.mkdir()

    with patch("second_brain.services.tavily.AsyncTavilyClient") as mock_cls, patch(
        "second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir
    ):
        mock_client = AsyncMock()
        mock_client.extract = AsyncMock(
            return_value={"results": [{"raw_content": "content"}]}
        )
        mock_cls.return_value = mock_client

        from second_brain.services.tavily import crawl_and_save

        saved_path = await crawl_and_save("https://example.com/my-article")

    assert "example" in saved_path.name
    assert saved_path.name.endswith(".md")
