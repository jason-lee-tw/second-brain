import os
import re
from pathlib import Path

from tavily import AsyncTavilyClient

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
PENDING_DOCS_DIR = Path("temp/pending-digest-docs")


def _url_to_slug(url: str) -> str:
    """Convert a URL into a safe filename stem (max 80 chars)."""
    slug = re.sub(r"https?://", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug)
    return slug.strip("-")[:80]


async def crawl_url(url: str) -> str:
    """Extract markdown content from a URL via Tavily.

    Raises:
        ValueError: If Tavily returns no results for the URL.
    """
    client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
    response = await client.extract(urls=[url])
    results = response.get("results", [])
    if not results:
        raise ValueError(f"Tavily returned no content for URL: {url}")
    return results[0].get("raw_content", "")


async def crawl_and_save(url: str) -> Path:
    """Crawl a URL and save the content as a markdown file.

    Saves to PENDING_DOCS_DIR/<url-slug>.md and returns the Path.
    """
    content = await crawl_url(url)
    slug = _url_to_slug(url)
    filepath = PENDING_DOCS_DIR / f"{slug}.md"
    PENDING_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    return filepath
