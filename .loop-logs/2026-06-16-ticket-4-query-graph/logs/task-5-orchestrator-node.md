# Task 5 Log: Orchestrator Node

## Task Context

### Plan Section
### Task 5: Orchestrator Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/orchestrator.py`
- Create: `apps/backend/tests/unit/test_nodes/test_orchestrator.py`

**Dependency:** `pip install langchain-anthropic` — and ensure `ANTHROPIC_API_KEY` is set in `.env`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.orchestrator import route_query
from tests.unit.conftest import make_state


def _mock_routing(decision: str):
    """Helper: create a mock RoutingOutput with the given routing_decision."""
    mock_result = MagicMock()
    mock_result.routing_decision = decision
    return mock_result


@pytest.mark.asyncio
async def test_routes_to_rag_for_personal_knowledge_query():
    state = make_state(
        messages=[HumanMessage(content="What are my notes on machine learning?")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("rag"))
        result = await route_query(state)
    assert result["routing_decision"] == "rag"


@pytest.mark.asyncio
async def test_routes_to_web_for_current_events():
    state = make_state(
        messages=[HumanMessage(content="What happened in the tech industry this week?")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("web"))
        result = await route_query(state)
    assert result["routing_decision"] == "web"


@pytest.mark.asyncio
async def test_routes_to_both_for_mixed_query():
    state = make_state(
        messages=[HumanMessage(content="Compare my notes on Python with the latest Python 4 news.")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("both"))
        result = await route_query(state)
    assert result["routing_decision"] == "both"


@pytest.mark.asyncio
async def test_routes_to_neither_for_conversational_query():
    state = make_state(
        messages=[HumanMessage(content="Thanks, that helps!")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
        result = await route_query(state)
    assert result["routing_decision"] == "neither"


@pytest.mark.asyncio
async def test_includes_memory_context_in_prompt():
    """Verify that retrieved_memory facts are passed to the LLM."""
    state = make_state(
        messages=[HumanMessage(content="What do I know about Rust?")],
        retrieved_memory=[
            {"id": "1", "fact": "User prefers Rust for systems programming", "confidence": 0.9, "type": "learned_fact"}
        ],
    )
    captured_prompts = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return _mock_routing("rag")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = capture_invoke
        await route_query(state)

    assert len(captured_prompts) == 1
    assert "User prefers Rust for systems programming" in captured_prompts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_orchestrator.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.orchestrator`.

- [ ] **Step 3: Implement the orchestrator**

```python
# apps/backend/src/second_brain/nodes/orchestrator.py
from typing import Literal
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from second_brain.graphs.state import SecondBrainState

_ROUTING_PROMPT = """\
You are a query router for a personal knowledge management system (Second Brain).

Given the user's query and any relevant memory context retrieved from long-term storage,
decide the best retrieval strategy:

  "rag"     — query asks about the user's personal notes, documents, or ingested knowledge
  "web"     — query requires current/real-time information from the internet
  "both"    — query benefits from both personal knowledge and web search
  "neither" — query is purely conversational and can be answered from context alone

User memory context (from long-term storage):
{memory_context}

User query: {query}

Choose the routing_decision that best serves the user."""


class _RoutingOutput(BaseModel):
    routing_decision: Literal["rag", "web", "both", "neither"]
    reasoning: str


_structured_llm = ChatAnthropic(model="claude-haiku-4-5").with_structured_output(_RoutingOutput)


async def route_query(state: SecondBrainState) -> dict:
    """Graph node: LLM-powered routing using claude-haiku-4-5.

    Reads messages[-1].content and retrieved_memory, outputs routing_decision.
    """
    query = state["messages"][-1].content
    memory = state.get("retrieved_memory", [])
    memory_context = (
        "\n".join(f"- {m['fact']}" for m in memory)
        if memory
        else "No memory context available."
    )
    prompt = _ROUTING_PROMPT.format(memory_context=memory_context, query=query)
    result: _RoutingOutput = await _structured_llm.ainvoke(prompt)
    return {"routing_decision": result.routing_decision}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_orchestrator.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/orchestrator.py \
  tests/unit/test_nodes/test_orchestrator.py
git commit -m "feat(nodes): add Orchestrator node with claude-haiku-4-5 structured routing"
```

> **Note (adjustment applied for this repo):** This repo's convention (see `ingestion_agent.py`) sources credentials
> explicitly from `settings` rather than relying on an ambient env var. The implementation below constructs
> `ChatAnthropic(model="claude-haiku-4-5", anthropic_api_key=settings.anthropic_api_key)`, passing the `SecretStr`
> directly (no `.get_secret_value()` needed — `ChatAnthropic`'s field accepts `SecretStr`). No new Settings field
> was added for the model name; it stays a hardcoded literal per the coordinating instructions, to avoid merge
> conflicts with sibling tasks touching config.py in the same round.

This is the routing mechanism other Query Graph ACs depend on — no direct numbered AC is attached to this task itself.

---

## Attempt 1 — 2026-07-20T05:05:26Z

### Implementation Plan
- Write the 5 failing tests from the plan's Step 1 at `apps/backend/tests/unit/test_nodes/test_orchestrator.py`
- Run `just test-unit`, confirm `ModuleNotFoundError` for `second_brain.nodes.orchestrator`
- Implement `second_brain/nodes/orchestrator.py` per plan Step 3, adjusted to source the Anthropic API key explicitly from `settings.anthropic_api_key` (repo convention) instead of relying on an ambient env var
- Run `just lint` then `just test-unit`, fix any line-length violations
- Update TASK_JSON, commit

### Files Changed
- created `apps/backend/tests/unit/test_nodes/test_orchestrator.py` — 5 tests covering rag/web/both/neither routing + memory-context-in-prompt assertion
- created `apps/backend/src/second_brain/nodes/orchestrator.py` — `_RoutingOutput` pydantic model, module-level `_structured_llm` (`ChatAnthropic(model="claude-haiku-4-5", anthropic_api_key=settings.anthropic_api_key)`.with_structured_output), `async def route_query`

### New Tests
- `test_routes_to_rag_for_personal_knowledge_query`
- `test_routes_to_web_for_current_events`
- `test_routes_to_both_for_mixed_query`
- `test_routes_to_neither_for_conversational_query`
- `test_includes_memory_context_in_prompt`

### Key Decisions
- Passed `settings.anthropic_api_key` (a `SecretStr`) directly to `ChatAnthropic`'s `anthropic_api_key` field rather than calling `.get_secret_value()` — `ChatAnthropic` accepts `SecretStr` natively, and this differs from `ingestion_agent.py`'s raw `anthropic.AsyncAnthropic` client only because that SDK's `api_key` param is a plain string. Both follow the same underlying convention: never rely on ambient `ANTHROPIC_API_KEY`, always source explicitly from `settings`.
- Kept `"claude-haiku-4-5"` as a hardcoded literal (no new `Settings` field) per the coordinating instructions, to avoid merge conflicts with sibling tasks touching `config.py` in the same round.

### Lint Output
PASS

### Test Output
PASS (99 passed, 5 new)

### Commit
`0cfe55a`

### Outcome: success
