"""Web Research node: queries Tavily search API with 1 req/sec rate limiting."""
import asyncio

from tavily import TavilyClient

from second_brain.config import settings
from second_brain.graphs.state import SecondBrainState


async def search_web(state: SecondBrainState) -> dict:
    """Search the web using Tavily and return up to 3 results.

    Rate-limited to 1 request per second via asyncio.sleep(1).
    """
    query = state["messages"][-1].content
    await asyncio.sleep(1)  # rate limit: 1 call/sec
    client = TavilyClient(api_key=settings.tavily_api_key.get_secret_value())
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, lambda: client.search(query, max_results=3)
    )
    web_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in response.get("results", [])
    ]
    return {"web_results": web_results}
