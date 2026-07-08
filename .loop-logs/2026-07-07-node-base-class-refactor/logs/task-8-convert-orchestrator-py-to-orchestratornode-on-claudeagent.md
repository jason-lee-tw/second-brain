# Task 8 Log: Convert orchestrator.py to OrchestratorNode

## Task Context

### Plan Section

### Task 8: Convert `orchestrator.py` to `OrchestratorNode` (on `ClaudeAgent`)

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/orchestrator.py`
- Modify: `apps/backend/tests/unit/test_nodes/test_orchestrator.py`

**Interfaces:**
- Consumes: `CLAUDE_MODEL_NAME`, `ClaudeAgent` from `second_brain.nodes.base_node.agents` (Task 1).
- Produces: `route_query` (instance of `OrchestratorNode`, `async def __call__`), with a `_structured_llm` instance attribute (cached `ClaudeAgent(HAIKU).get_model().with_structured_output(_RoutingOutput)`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/orchestrator.py`:

```python
# apps/backend/src/second_brain/nodes/orchestrator.py
from typing import Literal, override

from pydantic import BaseModel

from second_brain.graphs.state import RouteQueryOutput, SecondBrainState
from second_brain.nodes.base_node import BaseAgentNode
from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent
from second_brain.utils import get_str_content

_ROUTING_PROMPT = """\
You are a query router for a personal knowledge management system (Second Brain).

Given the user's query and any relevant memory context retrieved from long-term storage,
decide the best retrieval strategy:

  "rag"     — query asks about the user's personal notes, documents, or ingested
              knowledge
  "web"     — query requires current/real-time information from the internet
  "both"    — query benefits from both personal knowledge and web search
  "neither" — query is purely conversational and can be answered from context alone

User memory context (from long-term storage):
{memory_context}

User query: {query}

Choose the routing_decision that best serves the user."""


class _RoutingOutput(BaseModel):
  routing_decision: Literal["rag", "web", "both", "neither"]


class OrchestratorNode(BaseAgentNode[SecondBrainState, RouteQueryOutput]):
  """LLM-powered routing using claude-haiku-4-5."""

  def __init__(self):
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU))
    self._structured_llm = self._agent.get_model().with_structured_output(
      _RoutingOutput
    )

  @override
  async def __call__(self, state: SecondBrainState) -> RouteQueryOutput:
    """Reads messages[-1].content and retrieved_memory, outputs routing_decision."""
    query = get_str_content(state["messages"][-1])
    memory = state.get("retrieved_memory", [])
    memory_context = (
      "\n".join(f"- {m['fact']}" for m in memory)
      if memory
      else "No memory context available."
    )
    prompt = _ROUTING_PROMPT.format(memory_context=memory_context, query=query)
    result: _RoutingOutput = await self._structured_llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]
    return {"routing_decision": result.routing_decision}


route_query = OrchestratorNode()
```

If `basedpyright` flags the `ClaudeAgent(...)` call or `.with_structured_output(...)` call in Step 4 below, add the narrowest `# pyright: ignore[<code>]` comment on that exact line rather than a blanket ignore — match the style already used elsewhere in this file (see the `# pyright: ignore[reportAssignmentType]` on the `ainvoke` line, kept from the original).

- [ ] **Step 2: Update the test file's patch targets**

In `apps/backend/tests/unit/test_nodes/test_orchestrator.py`, replace every occurrence of:

```python
  with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
```

with:

```python
  with patch("second_brain.nodes.orchestrator.route_query._structured_llm") as mock_llm:
```

This occurs 5 times (lines 24, 36, 50, 62, 88 in the current file). No other lines in this file change.

- [ ] **Step 3: Run the test file, confirm PASS**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_orchestrator.py -v`
Expected: 5 passed, 0 failed.

- [ ] **Step 4: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors (see the note in Step 1 if `basedpyright` complains).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/orchestrator.py apps/backend/tests/unit/test_nodes/test_orchestrator.py
git commit -m "refactor: convert orchestrator node to BaseAgentNode on ClaudeAgent"
```

### Acceptance Criteria
- `route_query` becomes an instance of `OrchestratorNode` built on `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)`.
- 5 patch targets in test file updated from `second_brain.nodes.orchestrator._structured_llm` to `second_brain.nodes.orchestrator.route_query._structured_llm`.
- Test file passes 5/5.
- `just lint && just type-check` clean.

## Attempt 1

### Implementation Plan
Apply the exact source replacement from the plan (Task 8 Step 1) to
`apps/backend/src/second_brain/nodes/orchestrator.py`, converting the module-level
`route_query` function + module-level `_structured_llm` into an `OrchestratorNode(BaseAgentNode)`
class instantiated as `route_query = OrchestratorNode()`, built on
`ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)`. Then update the 5 patch targets in the test file
per Step 2 (`second_brain.nodes.orchestrator._structured_llm` ->
`second_brain.nodes.orchestrator.route_query._structured_llm`).

### Files Changed
- `apps/backend/src/second_brain/nodes/orchestrator.py` — full-file replacement per plan.
- `apps/backend/tests/unit/test_nodes/test_orchestrator.py` — 5 `patch(...)` target string
  edits via `sed`, no other changes.

### New Tests
None (plan explicitly notes existing test file coverage is sufficient once patch targets
are updated one attribute deeper).

### Key Decisions
- Used plan's source verbatim; no deviation needed — `BaseAgentNode`, `BaseAgent.get_model()`,
  `CLAUDE_MODEL_NAME`, `ClaudeAgent` all already existed exactly as the plan assumed (from
  Task 1, already merged into this worktree's base commit `221ac94`).
- No `# pyright: ignore` needed on `ClaudeAgent(...)` or `.with_structured_output(...)` —
  basedpyright reported 0 errors/0 warnings, so the contingency note in Step 1 didn't apply.

### Lint Output
`just lint` -> "All checks passed!"

### Type-check Output
`just type-check` -> "0 errors, 0 warnings, 8 notes" (the 8 informational notes are all in
unrelated pre-existing files `memory_persistence.py` / `memory_retrieval.py`, not touched by
this task) -> "✅ Type check is completed"

### Test Output
`uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_orchestrator.py -v`
-> 5 passed, 1 warning (unrelated LangChainPendingDeprecationWarning) in 3.77s:
- test_routes_to_rag_for_personal_knowledge_query PASSED
- test_routes_to_web_for_current_events PASSED
- test_routes_to_both_for_mixed_query PASSED
- test_routes_to_neither_for_conversational_query PASSED
- test_includes_memory_context_in_prompt PASSED

### Commit
`25d7b4f refactor: convert orchestrator node to BaseAgentNode on ClaudeAgent`
(pre-commit hook re-ran lint + type-check + commit-msg format check, all passed)

### Outcome
PASS on attempt 1.
