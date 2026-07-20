import hashlib
import re
from pathlib import Path

from tavily import AsyncTavilyClient

from second_brain.config import settings

PENDING_DOCS_DIR = settings.pending_docs_dir  # patchable in tests

_client = AsyncTavilyClient(api_key=settings.tavily_api_key.get_secret_value())


def url_to_slug(url: str) -> str:
    """Convert a URL into a safe filename stem (max 80 chars)."""
    slug = re.sub(r"https?://", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug)
    return slug[:80].strip("-")  # strip AFTER slice to avoid trailing dash


async def crawl_url(url: str) -> str:
    """Extract markdown content from a URL via Tavily.

    Raises:
        ValueError: If Tavily returns no results for the URL.
        ValueError: If Tavily returns empty content for the URL.
    """
    response = await _client.extract(urls=[url])
    results = response.get("results", [])
    if not results:
        raise ValueError(f"Tavily returned no content for URL: {url}")
    content = results[0].get("raw_content", "")
    if not content.strip():
        raise ValueError(f"Tavily returned empty content for URL: {url}")
    return content


async def crawl_and_save(url: str) -> Path:
    """Crawl a URL and save the content as a markdown file."""
    content = await crawl_url(url)
    slug = url_to_slug(url)
    hash8 = hashlib.sha256(url.encode()).hexdigest()[-8:]
    filepath = PENDING_DOCS_DIR / f"{slug}_{hash8}.md"
    PENDING_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    return filepath


async def search_web(query: str, max_results: int = 3) -> list[dict]:
    """Search the web via Tavily. Returns an empty list if there are no results."""
    response = await _client.search(query, max_results=max_results)
    return response.get("results", [])
