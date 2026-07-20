# Task 4 Log: MemoryRetrievalNode Stub

## Task Context

### Plan Section
### Task 4: MemoryRetrievalNode Stub

**Files:**
- Create: `apps/backend/src/second_brain/nodes/memory_retrieval.py`

> This is a stub for Ticket 4. The full pgvector similarity search across `learned_facts` and `model_corrections` is implemented in Ticket 5. The stub wires the node into the graph so Ticket 5 can drop in the real implementation with no graph changes.

- [ ] **Step 1: Write a minimal test**

```python
# Add to apps/backend/tests/unit/test_nodes/test_pii_redaction.py
# (or create a separate file — add to the existing test_nodes module)

# apps/backend/tests/unit/test_nodes/test_memory_retrieval.py
import pytest
from second_brain.nodes.memory_retrieval import retrieve_memory
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_retrieve_memory_stub_returns_empty_list():
    state = make_state()
    result = await retrieve_memory(state)
    assert result == {"retrieved_memory": []}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.memory_retrieval`.

- [ ] **Step 3: Implement the stub**

```python
# apps/backend/src/second_brain/nodes/memory_retrieval.py
from second_brain.graphs.state import SecondBrainState


async def retrieve_memory(state: SecondBrainState) -> dict:
    """Stub: returns empty list. Full implementation in Ticket 5.

    Ticket 5 will implement cosine similarity search on `learned_facts`
    and `model_corrections` tables, populating `retrieved_memory` with
    relevant MemoryItem entries for the current query.
    """
    return {"retrieved_memory": []}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/memory_retrieval.py \
  tests/unit/test_nodes/test_memory_retrieval.py
git commit -m "feat(nodes): add MemoryRetrievalNode stub (full impl in Ticket 5)"
```

No direct AC — foundational wiring for later tickets (Ticket 5 real impl, Task 9 graph wiring).

## Attempt 1 — 2026-07-20T05:02:27Z

### Implementation Plan
- Write failing async test asserting `retrieve_memory(make_state())` returns `{"retrieved_memory": []}`
- Run `just test-unit` to confirm ModuleNotFoundError for `second_brain.nodes.memory_retrieval`
- Implement `retrieve_memory` stub returning empty list with a one-line "why" comment
- Run `just lint` then `just test-unit`, fix any lint line-length issues

### Files Changed
- created `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py` — failing-first async test for the stub
- created `apps/backend/src/second_brain/nodes/memory_retrieval.py` — async no-op `retrieve_memory` node stub

### New Tests
- `test_retrieve_memory_stub_returns_empty_list`

### Key Decisions
- Used a one-line docstring instead of the plan's multi-line docstring to keep the "why" brief per task instructions, trimming it twice to satisfy ruff's 88-char E501 limit

### Lint Output
PASS

### Test Output
PASS (95 passed, 1 new)

### Commit
`11d2c54`

### Outcome: success
