# Task 9 Log: Convert memory_agent.py to MemoryAgentNode

## Task Context

- Task ID: task-9-convert-memory_agent-py-to-memoryagentnode-on-claudeagent
- Worktree: .worktrees/task-9-convert-memory_agent-py-to-memoryagentnode-on-claudeagent
- Branch: worktree/task-9-convert-memory_agent-py-to-memoryagentnode-on-claudeagent
- Branches from current HEAD (includes Task 1's BaseNode/BaseAgentNode fix + CLAUDE_MODEL_NAME export).

### Plan Section

### Task 9: Convert `memory_agent.py` to `MemoryAgentNode` (on `ClaudeAgent`)

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/memory_agent.py`
- Modify: `apps/backend/tests/unit/test_nodes/test_memory_agent.py`

**Interfaces:**
- Consumes: `CLAUDE_MODEL_NAME`, `ClaudeAgent` (Task 1).
- Produces: `memory_agent_node` (instance of `MemoryAgentNode`, `async def __call__`), with a `_llm` instance attribute (cached `ClaudeAgent(HAIKU).get_model().with_structured_output(MemoryAgentOutput)`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/memory_agent.py`:

```python
"""MemoryAgentNode: classifies user message into one of three MemoryCase values."""

from __future__ import annotations

from typing import override

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from second_brain.graphs.state import (
  ConflictContext,
  MemoryAgentOutput,
  SecondBrainState,
)
from second_brain.nodes.base_node import BaseAgentNode
from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent
from second_brain.utils import get_str_content, last_human_message


def _prior_ai_content(messages: list[BaseMessage]) -> str:
  last_human_idx: int | None = None
  for i in range(len(messages) - 1, -1, -1):
    if isinstance(messages[i], HumanMessage):
      last_human_idx = i
      break
  if last_human_idx is None or last_human_idx == 0:
    return ""
  for i in range(last_human_idx - 1, -1, -1):
    if isinstance(messages[i], AIMessage):
      return get_str_content(messages[i])
  return ""


class MemoryAgentNode(BaseAgentNode[SecondBrainState, dict[str, object]]):
  """Three-case memory classification via LangChain-Anthropic structured output."""

  def __init__(self):
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU))
    self._llm = self._agent.get_model().with_structured_output(MemoryAgentOutput)

  @override
  async def __call__(self, state: SecondBrainState) -> dict[str, object]:
    messages = state["messages"]
    awaiting_correction: bool = state.get("awaiting_correction", False)  # type: ignore[union-attr]
    awaiting_conflict: bool = state.get("awaiting_conflict_clarification", False)  # type: ignore[union-attr]
    conflict_context: list[ConflictContext] = state.get("conflict_context", [])  # type: ignore[union-attr]

    human_msg = last_human_message(messages)
    if human_msg is None:
      return {"fact_updates": [], "correction_updates": []}
    user_text = get_str_content(human_msg)

    if awaiting_conflict:
      # Case 3: conflict clarification — pass existing_ids so LLM can populate
      # conflicts_with; persistence uses that to delete replaced facts (F1 fix)
      conflict_summary = "\n".join(
        f'- existing_id={c["existing_id"]} | Existing: "{c["existing"]}"'
        f' | New: "{c["new"]}"'
        for c in conflict_context
      )
      prompt = (
        "The user previously had a memory conflict that needs clarifying.\n\n"
        f"Conflicts:\n{conflict_summary}\n\n"
        f"User clarification: {user_text!r}\n\n"
        "case=conflict_resolution. Populate fact_updates with the resolved "
        "fact(s). Set conflicts_with to the existing_id(s) of the facts being "
        "replaced — this triggers deletion of the old facts before writing "
        "the new one. If the user chose to keep the existing fact, return "
        "empty fact_updates."
      )
    elif awaiting_correction:
      # Case 2: correction check
      prior_ai = _prior_ai_content(messages)
      prompt = (
        f"The AI gave an uncertain answer: {prior_ai!r}\n"
        f"The user responded: {user_text!r}\n\n"
        "Decide: is the user explicitly correcting the AI's answer on the "
        "SAME topic, or are they asking a completely different question?\n\n"
        "CORRECTION (case=correction): user directly contradicts or fixes the "
        "AI's answer on the same topic (e.g. 'Actually it is X', 'You are "
        "wrong, the answer is Y'). Populate correction_updates with "
        "original_answer, correction, root_cause.\n\n"
        "NOT a correction (case=fact_extraction): user asks about a "
        "completely different topic, ignores the prior answer, or asks a "
        "question unrelated to what the AI was uncertain about. In this case "
        "extract any self-referential facts into fact_updates (or leave "
        "empty).\n\n"
        "If in doubt, prefer case=fact_extraction over case=correction."
      )
    else:
      # Case 1: normal fact extraction
      prompt = (
        f"User message: {user_text!r}\n\n"
        "case=fact_extraction. Extract self-referential facts (statements "
        "where the user describes themselves, e.g. 'I work as X', 'I live "
        "in Y', 'I prefer Z'). Return empty fact_updates if none exist. "
        "Set conflicts_with=[] for every fact."
      )

    output: MemoryAgentOutput = await self._llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]

    # F1 fix: in Case 3 the LLM may omit conflicts_with UUIDs (unreliable).
    # The pending_facts stored in state["fact_updates"] from the previous turn
    # already carry the correct conflicts_with — copy those over when empty so
    # _persist_fact can delete the replaced fact without re-running _conflict_check.
    fact_updates_out = list(output.fact_updates)
    if awaiting_conflict:
      pending_facts = state.get("fact_updates") or []  # type: ignore[union-attr]
      annotated = []
      for i, llm_fact in enumerate(fact_updates_out):
        if not llm_fact.get("conflicts_with") and i < len(pending_facts):
          annotated.append(
            {**llm_fact, "conflicts_with": pending_facts[i]["conflicts_with"]}
          )
        else:
          annotated.append(llm_fact)
      fact_updates_out = annotated

    updates: dict[str, object] = {
      "fact_updates": fact_updates_out,
      "correction_updates": list(output.correction_updates),
    }

    # State machine transitions
    if awaiting_conflict:
      # D4: mutually exclusive — reset both flags
      updates["awaiting_conflict_clarification"] = False
      updates["awaiting_correction"] = False
      updates["conflict_context"] = []
    elif awaiting_correction:
      updates["awaiting_correction"] = False

    return updates


memory_agent_node = MemoryAgentNode()
```

- [ ] **Step 2: Update the test file's patch targets**

In `apps/backend/tests/unit/test_nodes/test_memory_agent.py`, replace every occurrence of:

```python
  with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
```

with:

```python
  with patch("second_brain.nodes.memory_agent.memory_agent_node._llm") as mock_llm:
```

This occurs 6 times (lines 51, 80, 104, 141, 177, 224 in the current file). No other lines in this file change.

- [ ] **Step 3: Run the test file, confirm PASS**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_memory_agent.py -v`
Expected: 6 passed, 0 failed.

- [ ] **Step 4: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_agent.py apps/backend/tests/unit/test_nodes/test_memory_agent.py
git commit -m "refactor: convert memory_agent node to BaseAgentNode on ClaudeAgent"
```

### Acceptance Criteria

- Test file `test_memory_agent.py` passes 6/6 after patch-target update (one attribute deeper: `memory_agent.memory_agent_node._llm`).
- `just lint && just type-check` clean.

## Attempt 1

### Implementation Plan
Apply the plan's exact source-file replacement to `memory_agent.py` (module-level function + `_llm` global -> `MemoryAgentNode(BaseAgentNode[...])` class instantiated as `memory_agent_node`), then update the 6 test patch targets from `second_brain.nodes.memory_agent._llm` to `second_brain.nodes.memory_agent.memory_agent_node._llm`.

### Files Changed
- `apps/backend/src/second_brain/nodes/memory_agent.py` — full replacement per plan Step 1.
- `apps/backend/tests/unit/test_nodes/test_memory_agent.py` — 6 patch-target edits per plan Step 2.

### New Tests
None (existing test file's patch targets updated only).

### Key Decisions
- Followed plan verbatim; no deviations needed. `ClaudeAgent`, `CLAUDE_MODEL_NAME`, `BaseAgentNode` already available from Task 1's merged fix at worktree branch point.

### Lint Output
`just lint` -> "All checks passed!"

### Type-check Output
`just type-check` -> "0 errors, 0 warnings, 8 notes" (notes are pre-existing `reportUnknownArgumentType` informational notes in unrelated files `memory_persistence.py` / `memory_retrieval.py`, not introduced by this change).

### Test Output
`uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_memory_agent.py -v` -> 6 passed, 1 warning (pre-existing LangChainPendingDeprecationWarning, unrelated).

### Commit
`1b18cd6 refactor: convert memory_agent node to BaseAgentNode on ClaudeAgent` (pre-commit hooks: format/lint/type-check/commit-msg all passed).

### Outcome
PASS on attempt 1.
