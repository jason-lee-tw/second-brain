# Task 7 Log: Create nodes/pick_file.py, update ingestion_graph.py

## Task Context

- TASK_ID: task-7-create-nodes-pick_file-py-and-update-ingestion_graph-py
- Worktree: `.worktrees/task-7-create-nodes-pick_file-py-and-update-ingestion_graph-py`
- Branch: `worktree/task-7-create-nodes-pick_file-py-and-update-ingestion_graph-py`
- Base HEAD at worktree creation: `221ac94 fix: correct BaseNode/BaseAgentNode call contract, export model name` (Task 1 fix already merged in).

### Plan Section

```
### Task 7: Create `nodes/pick_file.py` and update `ingestion_graph.py`

**Files:**
- Create: `apps/backend/src/second_brain/nodes/pick_file.py`
- Modify: `apps/backend/src/second_brain/graphs/ingestion_graph.py`
- Test (no edits expected): `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py`, `apps/backend/tests/integration/test_ingestion_graph.py`

**Interfaces:**
- Produces: `pick_file_node` (instance of `PickFileNode`, sync `__call__`) importable from `second_brain.nodes.pick_file`.
- Consumes: nothing new — `IngestionState`/`PickFileOutput` already exist in `graphs/state.py`.

No test file directly imports `pick_file_node` (confirmed by repo search) — it's only exercised indirectly through `build_ingestion_graph().ainvoke(...)`, so this relocation needs no test edits.

- [ ] **Step 1: Create `nodes/pick_file.py`**

```python
"""PickFileNode: moves the next pending or retry file into in_progress."""

from typing import override

from second_brain.graphs.state import IngestionState, PickFileOutput
from second_brain.nodes.base_node import BaseNode


class PickFileNode(BaseNode[IngestionState, PickFileOutput]):
  """Move the next pending or retry file into in_progress.

  Priority: files[] (first-timers) before retry_queue.
  Does NOT remove the item from retry_queue — ingestion_agent_node does that
  after the attempt to preserve retry metadata for retry_count tracking.
  """

  @override
  def __call__(self, state: IngestionState) -> PickFileOutput:
    if state["files"]:
      return {
        "files": state["files"][1:],
        "in_progress": state["files"][0],
      }
    if state["retry_queue"]:
      return {
        "in_progress": state["retry_queue"][0]["filename"],
      }
    return {"in_progress": None}


pick_file_node = PickFileNode()
```

- [ ] **Step 2: Update `ingestion_graph.py`**

Replace the full contents of `apps/backend/src/second_brain/graphs/ingestion_graph.py`:

```python
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from second_brain.graphs.state import IngestionState
from second_brain.nodes.ingestion_agent import ingestion_agent_node
from second_brain.nodes.pick_file import pick_file_node


def _route_after_ingest(state: IngestionState) -> str:
  """Continue looping if there are more files or retries; else terminate."""
  if state["files"] or state["retry_queue"]:
    return "pick_file"
  return END


def build_ingestion_graph() -> CompiledStateGraph[
  IngestionState, None, IngestionState, IngestionState
]:
  builder = StateGraph(IngestionState)

  builder.add_node("pick_file", pick_file_node)
  builder.add_node("ingest", ingestion_agent_node)

  builder.set_entry_point("pick_file")
  builder.add_edge("pick_file", "ingest")
  builder.add_conditional_edges("ingest", _route_after_ingest)

  return builder.compile()


# Module-level singleton used by the API router
ingestion_graph = build_ingestion_graph()
```

- [ ] **Step 3: Run the graph test files to confirm still green**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_graphs/test_ingestion_graph.py -v`
Expected: all 4 tests pass (`_PATCH_TARGET = "second_brain.graphs.ingestion_graph.ingestion_agent_node"` still resolves — that import line is unchanged).

- [ ] **Step 4: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/pick_file.py apps/backend/src/second_brain/graphs/ingestion_graph.py
git commit -m "refactor: extract pick_file_node into nodes/ as a BaseNode subclass"
```
```

### Acceptance Criteria

None beyond the plan steps (pure structural move, no new tests expected).

## Attempt 1

### Implementation Plan
Follow plan verbatim: create `nodes/pick_file.py` with `PickFileNode(BaseNode[IngestionState, PickFileOutput])` wrapping the existing `pick_file_node` logic, then replace `graphs/ingestion_graph.py` to drop the inline function and import `pick_file_node` from the new module.

### Files Changed
- Created: `apps/backend/src/second_brain/nodes/pick_file.py`
- Modified: `apps/backend/src/second_brain/graphs/ingestion_graph.py` (removed inline `pick_file_node` function + `PickFileOutput` import, added `from second_brain.nodes.pick_file import pick_file_node`)

### New Tests
None (pure structural move; existing graph tests exercise the node indirectly via `build_ingestion_graph().ainvoke(...)`).

### Key Decisions
- Confirmed `BaseNode` is re-exported from the `second_brain.nodes.base_node` package `__init__.py` (it's a package, not a flat module) — `from second_brain.nodes.base_node import BaseNode` resolves correctly.
- Ran `uv sync --all-extras` in the fresh worktree venv first since `pytest`/`basedpyright` weren't installed yet.

### Lint Output
`just lint` → "All checks passed!"

### Test Output
`uv run --package second-brain pytest apps/backend/tests/unit/test_graphs/test_ingestion_graph.py -v` → 4 passed, 1 unrelated deprecation warning.

`just type-check` → 0 errors, 0 warnings, 8 informational notes (all pre-existing, in unrelated files `memory_persistence.py`/`memory_retrieval.py`, not touched by this task).

### Commit
`0f4a8c4 refactor: extract pick_file_node into nodes/ as a BaseNode subclass` (pre-commit hook re-ran format/lint/type-check/commit-msg checks, all passed).

### Outcome
PASS on attempt 1.
