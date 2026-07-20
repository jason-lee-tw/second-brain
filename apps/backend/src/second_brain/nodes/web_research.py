import asyncio

from second_brain.graphs.state import SecondBrainState, WebResult
from second_brain.services.tavily import search_web as tavily_search


async def search_web(state: SecondBrainState) -> dict:
    """Graph node: search the web via Tavily, max 3 results.

    Rate-limited to 1 call/second via asyncio.sleep(1) — Tavily search calls
    are throttled here in the node; the service function itself is unaware
    of rate limiting.
    """
    query = state["messages"][-1].content

    # Rate limit: max 1 Tavily call per second
    await asyncio.sleep(1)

    results = await tavily_search(query, max_results=3)

    web_results: list[WebResult] = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in results
    ]
    return {"web_results": web_results}
