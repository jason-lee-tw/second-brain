# Synthesis max_tokens Truncation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `POST /query` from 500ing when the synthesis LLM completion is truncated by `max_tokens` before a required structured-output field is written, and fix the identical latent defect in `MemoryAgentNode` in the same pass.

**Architecture:** Add one shared retry helper, `BaseAgentNode._ainvoke_structured`, that wraps a structured-output `Runnable`'s `.ainvoke()` call and retries exactly once on `pydantic.ValidationError`. Both `SynthesisNode` and `MemoryAgentNode` route their existing single `.ainvoke(prompt)` call through it, and both raise their `ClaudeAgent`'s `max_tokens` from the library default (1024) to 4096 so truncation becomes rare in the first place. The retry absorbs the residual case where it still happens.

**Tech Stack:** Python 3.13, LangChain/LangChain-Anthropic (`with_structured_output`), Pydantic v2, pytest + pytest-asyncio.

## Global Constraints

- `just format`, `just lint`, `just type-check`, `just test-unit` must all pass with no errors/warnings before any task is considered done (project CLAUDE.md "Done Means").
- TDD: write the failing test before the implementation for every task.
- Catch `pydantic.ValidationError` specifically — never a broad `except Exception` (project CLAUDE.md "no broad excepts").
- `max_tokens` changes are per-node, at `ClaudeAgent(...)` construction call sites only — `ClaudeAgent`'s own default-handling logic (`claude_agent.py`) is not modified, so unrelated call sites (`IngestionAgentNode`'s `max_tokens=150`, `OrchestratorNode`'s unset default) are unaffected.
- 2-space indentation, matching the rest of `apps/backend/src`.

---

### Task 1: `BaseAgentNode._ainvoke_structured` retry helper

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`
- Test: `apps/backend/tests/unit/test_nodes/test_base_agent_node.py` (new)

**Interfaces:**
- Produces: `BaseAgentNode._ainvoke_structured[T](self, structured_llm: Runnable[LanguageModelInput, T], prompt: str) -> T` — an async instance method. Tasks 2 and 3 call it as `await self._ainvoke_structured(self._structured_llm_attr, prompt)`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/test_nodes/test_base_agent_node.py`:

```python
"""Unit tests for BaseAgentNode._ainvoke_structured retry-on-truncation helper."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from second_brain.nodes.base_node.base_agent_node import BaseAgentNode


class _DummyOutput(BaseModel):
  value: str


class _DummyNode(BaseAgentNode[dict, dict]):
  async def __call__(self, state):  # pragma: no cover - not exercised here
    return {}


def _validation_error() -> ValidationError:
  """Build a real ValidationError the same way PydanticToolsParser triggers one."""
  try:
    _DummyOutput.model_validate({})
  except ValidationError as exc:
    return exc
  raise AssertionError("expected ValidationError")


@pytest.mark.asyncio
async def test_ainvoke_structured_returns_first_result_on_success():
  """A successful first call returns that result without a second call."""
  node = _DummyNode(MagicMock())
  structured_llm = MagicMock()
  structured_llm.ainvoke = AsyncMock(return_value=_DummyOutput(value="ok"))

  result = await node._ainvoke_structured(structured_llm, "prompt")

  assert result == _DummyOutput(value="ok")
  assert structured_llm.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_ainvoke_structured_retries_once_on_validation_error():
  """A ValidationError on the first call triggers exactly one retry."""
  node = _DummyNode(MagicMock())
  structured_llm = MagicMock()
  structured_llm.ainvoke = AsyncMock(
    side_effect=[_validation_error(), _DummyOutput(value="retried")]
  )

  result = await node._ainvoke_structured(structured_llm, "prompt")

  assert result == _DummyOutput(value="retried")
  assert structured_llm.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_ainvoke_structured_propagates_after_second_failure():
  """Two consecutive ValidationErrors propagate instead of being swallowed."""
  node = _DummyNode(MagicMock())
  structured_llm = MagicMock()
  structured_llm.ainvoke = AsyncMock(
    side_effect=[_validation_error(), _validation_error()]
  )

  with pytest.raises(ValidationError):
    await node._ainvoke_structured(structured_llm, "prompt")

  assert structured_llm.ainvoke.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/test_nodes/test_base_agent_node.py -v`
Expected: FAIL/ERROR — `AttributeError: '_DummyNode' object has no attribute '_ainvoke_structured'`

- [ ] **Step 3: Implement `_ainvoke_structured`**

Replace the full contents of `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`:

```python
from abc import ABC, abstractmethod
from collections.abc import Awaitable

from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from .agents import BaseAgent


class BaseAgentNode[InputStateType, ResultStateType](ABC):
  _agent: BaseAgent

  def __init__(self, agent: BaseAgent):
    super().__init__()
    self._agent = agent

  async def _ainvoke_structured[T](
    self, structured_llm: Runnable[LanguageModelInput, T], prompt: str
  ) -> T:
    """Invoke a structured-output Runnable, retrying once on ValidationError.

    Anthropic's tool-use `required` schema fields are advisory only — a
    completion truncated by max_tokens can omit one, which PydanticToolsParser
    surfaces as a ValidationError. One retry absorbs that transient
    truncation; a second failure means it isn't transient.
    """
    try:
      return await structured_llm.ainvoke(prompt)
    except ValidationError:
      return await structured_llm.ainvoke(prompt)

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/test_nodes/test_base_agent_node.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Type-check and lint**

Run: `cd apps/backend && uv run basedpyright ./src/ && uv run ruff check .`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/nodes/base_node/base_agent_node.py apps/backend/tests/unit/test_nodes/test_base_agent_node.py
git commit -m "fix: retry structured-output parse once on truncated ValidationError"
```

---

### Task 2: Wire `SynthesisNode` — raise max_tokens, use the retry helper

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/synthesis.py:45` and `:104`
- Test: `apps/backend/tests/unit/test_nodes/test_synthesis.py`

**Interfaces:**
- Consumes: `BaseAgentNode._ainvoke_structured` from Task 1.

- [ ] **Step 1: Write the failing tests**

Add to `apps/backend/tests/unit/test_nodes/test_synthesis.py` (add `ValidationError` to the existing `from unittest.mock import ...` / add a new import line, and `from unittest.mock import patch` is already imported):

```python
from pydantic import ValidationError
```

Then append these two tests:

```python
@patch("second_brain.nodes.base_node.agents.claude_agent.ChatAnthropic")
def test_synthesis_node_sets_max_tokens_4096(mock_chat_anthropic):
  """SynthesisNode must raise max_tokens above the 1024 library default.

  Regression guard for docs/bugs/004-synthesis-max-tokens-truncation.md —
  1024 truncated a verbose completion before the required `reasoning` field
  was written, causing an uncaught ValidationError -> 500.
  """
  from second_brain.nodes.synthesis import SynthesisNode

  SynthesisNode()

  _, kwargs = mock_chat_anthropic.call_args
  assert kwargs["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_synthesize_answer_retries_once_when_structured_output_is_truncated():
  """A ValidationError from a truncated completion (max_tokens) triggers one retry.

  Regression guard for docs/bugs/004-synthesis-max-tokens-truncation.md.
  """
  from second_brain.nodes.synthesis import _SynthesisOutput

  try:
    _SynthesisOutput.model_validate({"final_answer": "partial", "confidence": 0.75})
  except ValidationError as exc:
    truncated_error = exc
  else:
    raise AssertionError("expected ValidationError")

  mock_output = _make_synthesis_output(
    final_answer="Complete answer.", confidence=0.75, reasoning="Full reasoning."
  )
  state = make_state(
    messages=[HumanMessage(content="query")],
    routing_decision="rag",
    rag_results=[
      {"content": "context", "score": 0.9, "chunk_index": 0, "metadata": {}}
    ],
  )

  with patch(
    "second_brain.nodes.synthesis.synthesize_answer._structured_llm"
  ) as mock_llm:
    mock_llm.ainvoke = AsyncMock(side_effect=[truncated_error, mock_output])
    from second_brain.nodes.synthesis import synthesize_answer

    result = await synthesize_answer(state)

  assert result["final_answer"] == "Complete answer."
  assert mock_llm.ainvoke.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/test_nodes/test_synthesis.py -v`
Expected: `test_synthesis_node_sets_max_tokens_4096` FAILS (`kwargs["max_tokens"]` is `None`/missing); `test_synthesize_answer_retries_once_when_structured_output_is_truncated` FAILS by raising `ValidationError` out of `synthesize_answer` (no retry yet)

- [ ] **Step 3: Implement**

In `apps/backend/src/second_brain/nodes/synthesis.py`, change line 45:

```python
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None))
```
to:
```python
    super().__init__(
      ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None, max_tokens=4096)
    )
```

And change line 104:

```python
    output: _SynthesisOutput = await self._structured_llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]
```
to:
```python
    output: _SynthesisOutput = await self._ainvoke_structured(  # pyright: ignore[reportAssignmentType]
      self._structured_llm, prompt
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/test_nodes/test_synthesis.py -v`
Expected: PASS — all tests in the file, including the two new ones

- [ ] **Step 5: Run the full unit suite (regression check)**

Run: `cd apps/backend && uv run pytest tests/unit -v`
Expected: PASS — no other test broken by the `synthesis.py` change

- [ ] **Step 6: Type-check and lint**

Run: `cd apps/backend && uv run basedpyright ./src/ && uv run ruff check .`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/second_brain/nodes/synthesis.py apps/backend/tests/unit/test_nodes/test_synthesis.py
git commit -m "fix: raise SynthesisNode max_tokens to 4096 and retry truncated output"
```

---

### Task 3: Wire `MemoryAgentNode` — raise max_tokens, use the retry helper

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/memory_agent.py:37` and `:99`
- Test: `apps/backend/tests/unit/test_nodes/test_memory_agent.py`

**Interfaces:**
- Consumes: `BaseAgentNode._ainvoke_structured` from Task 1.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/unit/test_nodes/test_memory_agent.py` (add `patch` to the existing `from unittest.mock import AsyncMock, patch` import — already imported):

```python
@patch("second_brain.nodes.base_node.agents.claude_agent.ChatAnthropic")
def test_memory_agent_node_sets_max_tokens_4096(mock_chat_anthropic):
  """MemoryAgentNode must raise max_tokens above the 1024 library default.

  Same latent defect shape as docs/bugs/004-synthesis-max-tokens-truncation.md
  (required MemoryAgentOutput.case field, no max_tokens override) — fixed
  proactively even though it hasn't been observed to truncate yet.
  """
  from second_brain.nodes.memory_agent import MemoryAgentNode

  MemoryAgentNode()

  _, kwargs = mock_chat_anthropic.call_args
  assert kwargs["max_tokens"] == 4096
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_nodes/test_memory_agent.py -v`
Expected: FAIL — `kwargs["max_tokens"]` is `None`/missing

- [ ] **Step 3: Implement**

In `apps/backend/src/second_brain/nodes/memory_agent.py`, change line 37:

```python
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU))
```
to:
```python
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, max_tokens=4096))
```

And change line 99:

```python
    output: MemoryAgentOutput = await self._llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]
```
to:
```python
    output: MemoryAgentOutput = await self._ainvoke_structured(  # pyright: ignore[reportAssignmentType]
      self._llm, prompt
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/test_nodes/test_memory_agent.py -v`
Expected: PASS — all tests in the file, including the new one

- [ ] **Step 5: Run the full unit suite (regression check)**

Run: `cd apps/backend && uv run pytest tests/unit -v`
Expected: PASS — includes `test_ingestion_agent_node_caps_max_tokens_at_150` (proves `IngestionAgentNode`'s unrelated `max_tokens=150` call site is untouched) and every existing `test_memory_agent.py`/`test_synthesis.py` case (proves the happy path through `_ainvoke_structured` behaves exactly like the old direct `.ainvoke` call)

- [ ] **Step 6: Type-check and lint**

Run: `cd apps/backend && uv run basedpyright ./src/ && uv run ruff check .`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_agent.py apps/backend/tests/unit/test_nodes/test_memory_agent.py
git commit -m "fix: raise MemoryAgentNode max_tokens to 4096 and retry truncated output"
```

---

### Task 4: Runtime verification and bug-doc closeout

**Files:**
- Modify: `docs/bugs/004-synthesis-max-tokens-truncation.md` (Fix section)

**Interfaces:**
- Consumes: the running backend (`just up-all`) and the repro curl from the bug doc.

- [ ] **Step 1: Full workspace verification**

Run: `just format && just lint && just type-check && just test-unit`
Expected: all four pass with no errors/warnings (project "Done Means")

- [ ] **Step 2: Boot the backend**

Run: `just up-all`
Expected: backend, Postgres, Phoenix containers healthy; `curl -s localhost:3001/health` (or existing health check) returns success

- [ ] **Step 3: Replay the exact repro from the bug doc**

Run:
```bash
curl -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the bug causing the endpoint POST /query keep failing from responding to user?", "sessionId": null}'
```
Expected: HTTP 200 with a JSON body containing `answer`/`confidence` (not a 500)

- [ ] **Step 4: Update the bug doc's Fix section**

In `docs/bugs/004-synthesis-max-tokens-truncation.md`, replace:

```markdown
## Fix

Not yet implemented — see spec: `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md`.
```

with:

```markdown
## Fix

Implemented per `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md`
and `docs/superpowers/plans/2026-07-13-synthesis-max-tokens-truncation-fix.md`:

- `SynthesisNode` and `MemoryAgentNode` now construct their `ClaudeAgent` with
  `max_tokens=4096` (was: unset, defaulting to `ChatAnthropic`'s library default of 1024).
- `BaseAgentNode._ainvoke_structured` retries a structured-output `.ainvoke()` call
  exactly once on `pydantic.ValidationError`, absorbing residual truncation without
  masking a genuine second failure.

Verified: replaying the original repro curl against a fresh backend now returns 200.
```

- [ ] **Step 5: Commit**

```bash
git add docs/bugs/004-synthesis-max-tokens-truncation.md
git commit -m "docs: close out synthesis max_tokens truncation bug"
```
