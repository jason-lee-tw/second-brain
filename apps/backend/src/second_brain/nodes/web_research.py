"""Web Research node: queries Tavily search API."""

import asyncio

from tavily import TavilyClient

from second_brain.config import settings
from second_brain.graphs.state import SecondBrainState, WebResearchOutput
from second_brain.utils import get_str_content


async def search_web(state: SecondBrainState) -> WebResearchOutput:
    """Search the web using Tavily and return up to 3 results."""
    query = get_str_content(state["messages"][-1])
    client = TavilyClient(api_key=settings.tavily_api_key.get_secret_value())
    response = await asyncio.to_thread(lambda: client.search(query, max_results=3))
    web_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in response.get("results", [])
    ]
    return {"web_results": web_results}
