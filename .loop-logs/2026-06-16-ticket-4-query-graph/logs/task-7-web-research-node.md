# Task 7 Log: Web Research Node

## Task Context

### Plan Section
### Task 7: Web Research Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/web_research.py`
- Create: `apps/backend/tests/unit/test_nodes/test_web_research.py`

**Dependencies:** `pip install tavily-python` — and ensure `TAVILY_API_KEY` is set in `.env` and exposed via `settings.tavily_api_key`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_web_research.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.web_research import search_web
from tests.unit.conftest import make_state


_FAKE_TAVILY_RESPONSE = {
    "results": [
        {"title": "Python 4 Released", "url": "https://python.org/news", "content": "Python 4 adds new features..."},
        {"title": "PEP 999", "url": "https://peps.python.org/pep-0999", "content": "PEP 999 proposes..."},
    ]
}


@pytest.mark.asyncio
async def test_returns_web_results():
    state = make_state(messages=[HumanMessage(content="What is new in Python 4?")])

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock):
        mock_instance = MagicMock()
        mock_instance.search.return_value = _FAKE_TAVILY_RESPONSE
        MockClient.return_value = mock_instance

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

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_instance = MagicMock()
        mock_instance.search.return_value = {"results": []}
        MockClient.return_value = mock_instance

        await search_web(state)

    mock_sleep.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    state = make_state(messages=[HumanMessage(content="Something very obscure??")])

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock):
        mock_instance = MagicMock()
        mock_instance.search.return_value = {"results": []}
        MockClient.return_value = mock_instance

        result = await search_web(state)

    assert result["web_results"] == []


@pytest.mark.asyncio
async def test_searches_with_last_message_content():
    """Verify the query passed to Tavily is messages[-1].content."""
    state = make_state(messages=[HumanMessage(content="Rust 2025 edition features?")])
    captured_queries: list[str] = []

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock):
        mock_instance = MagicMock()

        def capture_search(query, max_results=3):
            captured_queries.append(query)
            return {"results": []}

        mock_instance.search.side_effect = capture_search
        MockClient.return_value = mock_instance

        await search_web(state)

    assert captured_queries == ["Rust 2025 edition features?"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_web_research.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.web_research`.

- [ ] **Step 3: Implement the web research node**

```python
# apps/backend/src/second_brain/nodes/web_research.py
import asyncio
from tavily import TavilyClient

from second_brain.core.config import settings
from second_brain.graphs.state import SecondBrainState, WebResult


async def search_web(state: SecondBrainState) -> dict:
    """Graph node: search the web via Tavily, max 3 results.

    Rate-limited to 1 call/second via asyncio.sleep(1).
    TavilyClient.search is synchronous; it runs in the default thread executor.
    """
    query = state["messages"][-1].content

    # Rate limit: max 1 Tavily call per second
    await asyncio.sleep(1)

    client = TavilyClient(api_key=settings.tavily_api_key)

    # Tavily SDK is synchronous — offload to executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.search(query, max_results=3),
    )

    web_results: list[WebResult] = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in response.get("results", [])
    ]
    return {"web_results": web_results}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_web_research.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/web_research.py \
  tests/unit/test_nodes/test_web_research.py
git commit -m "feat(nodes): add Web Research node with Tavily search, rate-limited to 1 rps"
```

---

### Acceptance Criteria
- AC-1: `search_web(state)` returns a dict with `web_results` shaped as a list of `WebResult` (`title`, `url`, `content`)
- AC-2: Rate limiting via `asyncio.sleep(1)` is awaited exactly once per call
- AC-3: Query used for the Tavily search is `state["messages"][-1].content`
- AC-4: Tavily search is called with `max_results=3`
- AC-5: Returns `web_results == []` when Tavily returns no results

**Note (repo-state deviation from plan's example code):** The plan's example code instantiates a synchronous `TavilyClient` per-call and bridges to an executor. This repo already has `apps/backend/src/second_brain/services/tavily.py` with a module-level `_client = AsyncTavilyClient(...)` used for `.extract()`. Per current repo conventions, this task instead adds an async `search_web` function to `services/tavily.py` that calls `_client.search(...)`, and the node in `nodes/web_research.py` imports and calls that service function (aliased to avoid name collision), owning the `asyncio.sleep(1)` rate limit itself. No second Tavily client is instantiated.

---

## Attempt 1 — 2026-07-20T00:00:00Z

### Implementation Plan
- Add `async def search_web(query, max_results=3)` to `services/tavily.py`, calling the existing module-level `_client.search(...)` (AsyncTavilyClient), returning `response.get("results", [])`
- Write failing tests first: 3 new tests appended to `test_services/test_tavily.py` for `search_web` (calls `_client.search` with query + max_results, empty list on no results, default `max_results=3`), and a new `test_nodes/test_web_research.py` with 4 tests for the node (returns `web_results` shaped as `WebResult`, `asyncio.sleep(1)` awaited once, query is `messages[-1].content`, `max_results=3`, empty list passthrough)
- Create `nodes/web_research.py` with `async def search_web(state) -> dict` that awaits `asyncio.sleep(1)` for rate limiting, then calls the service function (imported as `tavily_search` to avoid the name collision with the node's own `search_web`), and maps raw Tavily dicts into `WebResult` TypedDicts
- Run `just lint` then `just test-unit`, confirm both pass

### Files Changed
- created `apps/backend/src/second_brain/nodes/web_research.py` — graph node: rate-limited (1 rps) Tavily web search, returns `{"web_results": [...]}`
- modified `apps/backend/src/second_brain/services/tavily.py` — added `search_web(query, max_results=3)` calling the existing `_client.search(...)`
- created `apps/backend/tests/unit/test_nodes/test_web_research.py` — unit tests for the node
- modified `apps/backend/tests/unit/test_services/test_tavily.py` — added unit tests for `search_web` service function

### New Tests
- `test_search_web_calls_client_search_with_query_and_max_results`
- `test_search_web_returns_empty_list_when_no_results`
- `test_search_web_default_max_results_is_three`
- `test_returns_web_results`
- `test_rate_limit_sleep_called`
- `test_returns_empty_list_when_no_results`
- `test_searches_with_last_message_content_and_max_results_three`

### Key Decisions
- Rate limiting (`asyncio.sleep(1)`) lives in the node, not the service — the service function is a plain Tavily wrapper reusable outside the rate-limited graph context; the node owns graph-specific throttling policy
- Imported the service function as `tavily_search` inside `nodes/web_research.py` to avoid shadowing the node's own public `search_web` name within the same module
- No new Tavily client instantiated — reused the existing module-level `AsyncTavilyClient` in `services/tavily.py` (already used for `.extract()`), keeping a single client instance and avoiding a second sync/async bridge

### Lint Output
PASS

### Test Output
PASS (101 passed, 7 new)

### Commit
`b023fa3`

### Outcome: success
