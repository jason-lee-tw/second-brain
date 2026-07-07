from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_crawl_url_returns_raw_content():
  """crawl_url must return the raw_content string from Tavily extract."""
  with patch("second_brain.services.tavily._client") as mock_client:
    mock_client.extract = AsyncMock(
      return_value={"results": [{"raw_content": "# Scraped Page\n\nBody text here."}]}
    )
    from second_brain.services.tavily import crawl_url

    result = await crawl_url("https://example.com/article")

  assert result == "# Scraped Page\n\nBody text here."


@pytest.mark.asyncio
async def test_crawl_url_raises_when_no_results():
  """crawl_url must raise ValueError when Tavily returns empty results."""
  with patch("second_brain.services.tavily._client") as mock_client:
    mock_client.extract = AsyncMock(return_value={"results": []})

    from second_brain.services.tavily import crawl_url

    with pytest.raises(ValueError, match="no content"):
      await crawl_url("https://example.com/empty")


@pytest.mark.asyncio
async def test_crawl_and_save_writes_markdown_file(tmp_path):
  """crawl_and_save must save crawled content as a .md file and return its path."""
  pending_dir = tmp_path / "pending-digest-docs"
  pending_dir.mkdir()

  with (
    patch("second_brain.services.tavily._client") as mock_client,
    patch("second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir),
  ):
    mock_client.extract = AsyncMock(
      return_value={"results": [{"raw_content": "# Hello\n\nWorld."}]}
    )
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

  with (
    patch("second_brain.services.tavily._client") as mock_client,
    patch("second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir),
  ):
    mock_client.extract = AsyncMock(
      return_value={"results": [{"raw_content": "content"}]}
    )
    from second_brain.services.tavily import crawl_and_save

    saved_path = await crawl_and_save("https://example.com/my-article")

  assert "example" in saved_path.name
  assert saved_path.name.endswith(".md")


@pytest.mark.asyncio
async def test_crawl_url_raises_when_raw_content_is_empty_string():
  """crawl_url must raise ValueError when raw_content is an empty string."""
  with patch("second_brain.services.tavily._client") as mock_client:
    mock_client.extract = AsyncMock(return_value={"results": [{"raw_content": ""}]})
    from second_brain.services.tavily import crawl_url

    with pytest.raises(ValueError, match="empty content"):
      await crawl_url("https://example.com/empty-body")


@pytest.mark.asyncio
async def test_crawl_url_raises_when_raw_content_is_whitespace_only():
  """crawl_url must raise ValueError when raw_content is whitespace-only."""
  with patch("second_brain.services.tavily._client") as mock_client:
    mock_client.extract = AsyncMock(
      return_value={"results": [{"raw_content": "   \n\t"}]}
    )
    from second_brain.services.tavily import crawl_url

    with pytest.raises(ValueError, match="empty content"):
      await crawl_url("https://example.com/whitespace-body")


@pytest.mark.asyncio
async def test_crawl_and_save_collision_urls_produce_distinct_files(tmp_path):
  """Two URLs with same slug must land in different files via hash suffix."""
  pending_dir = tmp_path / "pending-digest-docs"
  pending_dir.mkdir()

  url1 = "https://example.com/" + "a" * 70 + "SUFFIX1"
  url2 = "https://example.com/" + "a" * 70 + "SUFFIX2"

  with (
    patch("second_brain.services.tavily._client") as mock_client,
    patch("second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir),
  ):
    mock_client.extract = AsyncMock(
      return_value={"results": [{"raw_content": "some content"}]}
    )
    from second_brain.services.tavily import crawl_and_save, url_to_slug

    # Confirm both URLs produce the same slug (collision scenario)
    assert url_to_slug(url1) == url_to_slug(url2)

    path1 = await crawl_and_save(url1)
    path2 = await crawl_and_save(url2)

  assert path1 != path2
  assert path1.exists()
  assert path2.exists()
