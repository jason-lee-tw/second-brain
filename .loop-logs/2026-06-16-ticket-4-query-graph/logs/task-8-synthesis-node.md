# Task 8 Log: Synthesis Node

## Task Context

### Plan Section
### Task 8: Synthesis Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/synthesis.py`
- Create: `apps/backend/tests/unit/test_nodes/test_synthesis.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_synthesis.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage
from second_brain.nodes.synthesis import synthesize_answer
from tests.unit.conftest import make_state


def _mock_synthesis(answer: str, confidence: float):
    mock = MagicMock()
    mock.final_answer = answer
    mock.confidence = confidence
    return mock


@pytest.mark.asyncio
async def test_returns_final_answer_and_confidence():
    state = make_state(
        messages=[HumanMessage(content="What is LangGraph?")],
        rag_results=[{"content": "LangGraph is a graph-based agent framework.", "score": 0.9, "chunk_index": 0, "metadata": {}}],
        web_results=[],
        retrieved_memory=[],
        routing_decision="rag",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("LangGraph is a framework for agents.", 0.85))
        result = await synthesize_answer(state)

    assert result["final_answer"] == "LangGraph is a framework for agents."
    assert result["confidence"] == 0.85
    assert result["is_uncertain"] is False


@pytest.mark.asyncio
async def test_is_uncertain_true_when_confidence_below_07():
    state = make_state(
        messages=[HumanMessage(content="What is the best diet?")],
        rag_results=[],
        web_results=[],
        retrieved_memory=[],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("It depends on the individual.", 0.65))
        result = await synthesize_answer(state)

    assert result["is_uncertain"] is True
    assert result["confidence"] == 0.65


@pytest.mark.asyncio
async def test_neither_routing_applies_confidence_floor_of_05():
    """AC: when routing_decision == 'neither', confidence is floored at 0.5."""
    state = make_state(
        messages=[HumanMessage(content="Hey there!")],
        rag_results=[],
        web_results=[],
        retrieved_memory=[],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        # LLM returns very low confidence (e.g. 0.2) — should be raised to 0.5
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("Hello! How can I help?", 0.2))
        result = await synthesize_answer(state)

    assert result["confidence"] == 0.5
    assert result["is_uncertain"] is True  # 0.5 < 0.7, still uncertain
    assert result["final_answer"] == "Hello! How can I help?"


@pytest.mark.asyncio
async def test_neither_routing_does_not_lower_confidence_above_floor():
    """If LLM returns confidence > 0.5 on 'neither' routing, keep the LLM value."""
    state = make_state(
        messages=[HumanMessage(content="What is 2 + 2?")],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("4", 0.99))
        result = await synthesize_answer(state)

    assert result["confidence"] == 0.99


@pytest.mark.asyncio
async def test_trims_messages_to_last_10():
    """Verify only the last 10 messages are included in the synthesis prompt."""
    messages = [HumanMessage(content=f"Message {i}") for i in range(15)]
    state = make_state(
        messages=messages,
        routing_decision="neither",
    )
    captured_prompts: list[str] = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return _mock_synthesis("answer", 0.8)

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = capture_invoke
        await synthesize_answer(state)

    # "Message 0" through "Message 4" should NOT be in the prompt
    assert "Message 0" not in captured_prompts[0]
    assert "Message 5" in captured_prompts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_synthesis.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.synthesis`.

- [ ] **Step 3: Implement the synthesis node**

```python
# apps/backend/src/second_brain/nodes/synthesis.py
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from second_brain.graphs.state import SecondBrainState

_SYNTHESIS_PROMPT = """\
You are a knowledgeable Second Brain assistant. Synthesize a comprehensive, accurate answer
from the available context. Be clear about what you know and don't know.

--- Retrieved documents ---
{rag_context}

--- Web search results ---
{web_context}

--- Long-term memory ---
{memory_context}

--- Conversation history (last 10 turns) ---
{conversation_history}

--- Current question ---
{query}

Provide a helpful answer and rate your confidence from 0.0 (no idea) to 1.0 (certain).
Base confidence on the quality and relevance of the above context."""


class _SynthesisOutput(BaseModel):
    final_answer: str
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0–1.0")
    reasoning: str


_UNCERTAINTY_THRESHOLD = 0.7
_NEITHER_CONFIDENCE_FLOOR = 0.5

_structured_llm = ChatAnthropic(model="claude-sonnet-4-6").with_structured_output(_SynthesisOutput)


def _format_messages(messages: list[BaseMessage]) -> str:
    parts = []
    for m in messages:
        role = "Human" if isinstance(m, HumanMessage) else "Assistant"
        parts.append(f"{role}: {m.content}")
    return "\n".join(parts) if parts else "(no prior conversation)"


async def synthesize_answer(state: SecondBrainState) -> dict:
    """Graph node: synthesize final answer using claude-sonnet-4-6.

    Combines rag_results + web_results + retrieved_memory + last 10 messages.
    Applies confidence floor of 0.5 when routing_decision == 'neither'.
    Sets is_uncertain=True when confidence < 0.7.
    """
    query = state["messages"][-1].content
    rag_results = state.get("rag_results", [])
    web_results = state.get("web_results", [])
    memory = state.get("retrieved_memory", [])
    routing = state.get("routing_decision", "neither")

    # Use last 10 messages, excluding the current query (which is the last one)
    history_messages = state["messages"][-10:-1]

    rag_context = (
        "\n\n".join(f"[Score: {r['score']:.2f}]\n{r['content']}" for r in rag_results)
        if rag_results
        else "No document context retrieved."
    )
    web_context = (
        "\n\n".join(f"[{r['title']}]({r['url']})\n{r['content']}" for r in web_results)
        if web_results
        else "No web results retrieved."
    )
    memory_context = (
        "\n".join(f"- {m['fact']}" for m in memory)
        if memory
        else "No memory context."
    )
    conversation_history = _format_messages(history_messages)

    prompt = _SYNTHESIS_PROMPT.format(
        rag_context=rag_context,
        web_context=web_context,
        memory_context=memory_context,
        conversation_history=conversation_history,
        query=query,
    )

    output: _SynthesisOutput = await _structured_llm.ainvoke(prompt)

    confidence = output.confidence
    # Apply floor for conversational turns where no external context was retrieved
    if routing == "neither":
        confidence = max(confidence, _NEITHER_CONFIDENCE_FLOOR)

    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_synthesis.py -v
```

### Acceptance Criteria
- AC-1: `synthesize_answer` returns `final_answer` and `confidence` derived from `_structured_llm.ainvoke` output
- AC-2: `is_uncertain=True` when `confidence < 0.7`
- AC-3: "neither" routing floors confidence at 0.5, and remains `is_uncertain=True` since 0.5 < 0.7
- AC-4: "neither" routing does not lower an already-high confidence (floor only raises, never lowers)
- AC-5: only the last 10 messages (excluding the current query) are included in the synthesis prompt

**Repo convention override (credential passing):** per task instructions, construct `ChatAnthropic(model="claude-sonnet-4-6", anthropic_api_key=settings.anthropic_api_key)` — sourcing the key explicitly from `settings` (matching `ingestion_agent.py`'s pattern) rather than relying on an ambient env var. `ChatAnthropic.anthropic_api_key` accepts the `SecretStr` directly, no `.get_secret_value()` needed. Model name stays the literal string `"claude-sonnet-4-6"` (no new Settings field).

---

## Attempt 1 — 2026-07-20T05:06:26Z

### Implementation Plan
- Write 5 failing tests at `apps/backend/tests/unit/test_nodes/test_synthesis.py` per plan Step 1, patching `second_brain.nodes.synthesis._structured_llm.ainvoke`
- Run `just test-unit` (via `uv sync --all-extras` first, since worktree venv was fresh) to confirm `ModuleNotFoundError` for `second_brain.nodes.synthesis`
- Implement `apps/backend/src/second_brain/nodes/synthesis.py` per plan Step 3, adjusted for the explicit-credential convention: `ChatAnthropic(model="claude-sonnet-4-6", anthropic_api_key=settings.anthropic_api_key)`
- Run `just lint` then full `just test-unit`, fix any lint findings (import sort, line length), confirm both exit 0

### Files Changed
- created `apps/backend/src/second_brain/nodes/synthesis.py` — `synthesize_answer` node: builds prompt from rag/web/memory/last-10-messages, calls `_structured_llm`, applies 0.5 confidence floor for `neither` routing, sets `is_uncertain` at the 0.7 threshold
- created `apps/backend/tests/unit/test_nodes/test_synthesis.py` — 5 unit tests for the node, mocking `_structured_llm.ainvoke`

### New Tests
- `test_returns_final_answer_and_confidence`
- `test_is_uncertain_true_when_confidence_below_07`
- `test_neither_routing_applies_confidence_floor_of_05`
- `test_neither_routing_does_not_lower_confidence_above_floor`
- `test_trims_messages_to_last_10`

### Key Decisions
- Sourced the Anthropic API key explicitly from `settings.anthropic_api_key` (a `SecretStr`) passed directly to `ChatAnthropic`'s `anthropic_api_key` field, rather than relying on an ambient `ANTHROPIC_API_KEY` env var — matches this repo's existing pattern in `ingestion_agent.py` and was an explicit task requirement to avoid merge conflicts with sibling tasks touching shared config in the same parallel round.
- Wrapped the long uncertainty-prompt sentence across two lines to satisfy ruff's E501 (line length 88) without changing prompt content or behavior.

### Lint Output
PASS

### Test Output
PASS (99 passed, 5 new)

### Commit
`ca3b406`

### Outcome: success
