# Task 1 Log: SecondBrainState TypedDicts + Unit Test Conftest

## Task Context

### Plan Section
### Task 1: SecondBrainState TypedDicts + Unit Test Conftest

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/state.py`
- Create: `apps/backend/tests/unit/conftest.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/unit/test_state_types.py
from second_brain.graphs.state import (
    RagResult,
    WebResult,
    MemoryItem,
    FactUpdate,
    CorrectionUpdate,
    SecondBrainState,
)
from langchain_core.messages import HumanMessage


def test_rag_result_structure():
    item: RagResult = {
        "content": "some content",
        "score": 0.85,
        "chunk_index": 0,
        "metadata": {"source": "doc.md"},
    }
    assert item["score"] == 0.85


def test_second_brain_state_structure():
    state: SecondBrainState = {
        "session_id": "abc-123",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    assert state["routing_decision"] == "neither"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_state_types.py -v
```

Expected: `ImportError` — `SecondBrainState` not defined yet.

- [ ] **Step 3: Add SecondBrainState TypedDicts to `graphs/state.py`**

Open `apps/backend/src/second_brain/graphs/state.py`. Keep any existing content (e.g., `IngestionState`) and append the following:

```python
# apps/backend/src/second_brain/graphs/state.py
# --- append below existing IngestionState content ---

from typing import Annotated, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class RagResult(TypedDict):
    content: str
    score: float
    chunk_index: int
    metadata: dict


class WebResult(TypedDict):
    title: str
    url: str
    content: str


class MemoryItem(TypedDict):
    id: str
    fact: str
    confidence: float
    type: Literal["learned_fact", "model_correction"]


class FactUpdate(TypedDict):
    fact: str
    confidence: float
    conflicts_with: list[str]  # IDs of conflicting existing facts


class CorrectionUpdate(TypedDict):
    original_answer: str  # from messages[-2] (prior assistant response)
    correction: str
    root_cause: str


class SecondBrainState(TypedDict):
    session_id: str
    # Annotated with add_messages so LangGraph appends new messages
    # to the checkpoint rather than overwriting — required for session continuity (AC-10)
    messages: Annotated[list[BaseMessage], add_messages]
    rag_results: list[RagResult]
    web_results: list[WebResult]
    retrieved_memory: list[MemoryItem]
    routing_decision: Literal["rag", "web", "both", "neither"]
    final_answer: str
    confidence: float
    is_uncertain: bool
    awaiting_correction: bool        # persisted across turns via LangGraph checkpointing
    awaiting_conflict_clarification: bool
    conflict_context: list[str]
    fact_updates: list[FactUpdate]   # populated by Memory Agent (Ticket 5)
    correction_updates: list[CorrectionUpdate]  # populated by Memory Agent (Ticket 5)
```

> **Note:** The `TypedDict` import must already be at the top of `state.py` from the `IngestionState` definitions in Ticket 3. If not, add `from typing import TypedDict` to the top.

- [ ] **Step 4: Create the unit test conftest with `make_state` factory**

```python
# apps/backend/tests/unit/conftest.py
import pytest
from langchain_core.messages import HumanMessage
from second_brain.graphs.state import SecondBrainState


def make_state(**overrides) -> SecondBrainState:
    """Factory for SecondBrainState with safe defaults. Pass keyword args to override."""
    defaults: SecondBrainState = {
        "session_id": "test-session-001",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.9,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    defaults.update(overrides)  # type: ignore[typeddict-item]
    return defaults
```

- [ ] **Step 5: Run all state tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_state_types.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/graphs/state.py \
  tests/unit/conftest.py \
  tests/unit/test_state_types.py
git commit -m "feat(state): add SecondBrainState TypedDicts with add_messages reducer"
```

---

### Acceptance Criteria
No direct AC — foundational typing for later tasks.

## Repo Convention Deviations Applied

The plan above was written slightly out of sync with how this repo actually evolved. Per orchestrator instructions, the following deviations from the plan's literal file paths/code were applied:

1. `apps/backend/src/second_brain/graphs/state.py` already exists with `FailedFile`/`IngestionState` — new TypedDicts appended below existing content, not overwritten.
2. No fresh `tests/unit/test_state_types.py` was created — the two new test functions were appended into the EXISTING `apps/backend/tests/unit/test_graphs/test_state.py` (alongside existing `IngestionState`/`FailedFile` tests).
3. `apps/backend/tests/unit/conftest.py` did not exist — created fresh exactly per the plan's Step 4.
4. No `@pytest.mark.asyncio` needed (asyncio_mode = auto, and no async code here).
5. Matched existing style: no docstrings, short `#` inline comments only.

---

## Attempt 1 — 2026-07-20T04:52:18Z

### Implementation Plan
- Append `test_rag_result_structure` and `test_second_brain_state_structure` into existing `apps/backend/tests/unit/test_graphs/test_state.py`, adding only imports actually used (`RagResult`, `SecondBrainState`, `HumanMessage`) to keep ruff happy
- Create `apps/backend/tests/unit/conftest.py` fresh with the `make_state()` factory (dropped plan's unused `import pytest`)
- Run `just test-unit` to confirm ImportError on `SecondBrainState` (not yet defined)
- Append `RagResult`, `WebResult`, `MemoryItem`, `FactUpdate`, `CorrectionUpdate`, `SecondBrainState` TypedDicts to existing `apps/backend/src/second_brain/graphs/state.py` below `IngestionState`, adding `Annotated`, `Literal` to the existing `typing` import and new `BaseMessage`/`add_messages` imports
- Run `just lint` then `just test-unit`, fix any lint findings, commit

### Files Changed
- modified `apps/backend/src/second_brain/graphs/state.py` — appended `RagResult`, `WebResult`, `MemoryItem`, `FactUpdate`, `CorrectionUpdate`, `SecondBrainState` TypedDicts below existing `FailedFile`/`IngestionState`
- modified `apps/backend/tests/unit/test_graphs/test_state.py` — appended two new tests alongside existing `IngestionState`/`FailedFile` tests
- created `apps/backend/tests/unit/conftest.py` — `make_state()` factory for `SecondBrainState` with safe defaults

### New Tests
- `test_rag_result_structure`
- `test_second_brain_state_structure`

### Key Decisions
- Ran `just init` first — worktree's `uv` env had no `pytest` binary installed yet (fresh worktree, deps not synced); this is routine setup, not a task deviation.
- Did not import `WebResult`, `MemoryItem`, `FactUpdate`, `CorrectionUpdate`, `pytest` in test/conftest files as the plan's snippet did, since neither new test function nor `make_state()` references them — importing unused names would fail ruff `F401`.
- Wrapped one `#` comment across two lines and shortened a docstring to fix two `E501` line-too-long findings from `just lint` (89 > 88 chars) — mechanical fix, no semantic change.

### Lint Output
PASS

### Test Output
PASS (87 passed, 2 new)

### Commit
`829a02b`

### Outcome: success
