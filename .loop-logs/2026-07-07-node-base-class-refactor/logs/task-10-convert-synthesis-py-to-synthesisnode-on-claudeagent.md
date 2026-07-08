# Task 10 Log: Convert synthesis.py to SynthesisNode

## Task Context

Convert `apps/backend/src/second_brain/nodes/synthesis.py` from a module-level
function/global `_structured_llm` to a `SynthesisNode(BaseAgentNode)` class instance
built on `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET)`. This also fixes model-string drift
from a stale hardcoded `"claude-sonnet-4-6"` string to `CLAUDE_MODEL_NAME.SONNET`
(spec decision 2). `_format_messages` stays a module-level function since it doesn't
touch `self` and tests import it directly.

### Plan Section (verbatim)

### Task 10: Convert `synthesis.py` to `SynthesisNode` (on `ClaudeAgent`)

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/synthesis.py`
- Modify: `apps/backend/tests/unit/test_nodes/test_synthesis.py`

**Interfaces:**
- Consumes: `CLAUDE_MODEL_NAME`, `ClaudeAgent` (Task 1).
- Produces: `synthesize_answer` (instance of `SynthesisNode`, `async def __call__`), with a `_structured_llm` instance attribute (cached `ClaudeAgent(SONNET).get_model().with_structured_output(_SynthesisOutput)`). `_format_messages` stays a module-level function — the tests import it directly (`from second_brain.nodes.synthesis import _format_messages`) and it doesn't touch `self`.

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/synthesis.py`:

```python
"""Synthesis node: generates a final answer with confidence scoring."""

from typing import override

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from second_brain.graphs.state import SecondBrainState, SynthesisNodeOutput
from second_brain.nodes.base_node import BaseAgentNode
from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent
from second_brain.utils import get_str_content

_UNCERTAINTY_THRESHOLD = 0.7
# "neither" route = no external retrieval attempted; assume baseline confidence
# since LLM answered from context alone
_NEITHER_CONFIDENCE_FLOOR = 0.5


class _SynthesisOutput(BaseModel):
  final_answer: str
  confidence: float = Field(ge=0.0, le=1.0)
  reasoning: str


def _format_messages(messages: list[BaseMessage]) -> str:
  """Format a list of HumanMessage/AIMessage to a readable string.

  Messages are expected to have string content; raises on multi-modal content.
  """
  parts: list[str] = []
  for msg in messages:
    if isinstance(msg, HumanMessage):
      parts.append(f"User: {get_str_content(msg)}")
    elif isinstance(msg, AIMessage):
      parts.append(f"Assistant: {get_str_content(msg)}")
    else:
      parts.append(f"[{type(msg).__name__}]: {get_str_content(msg)}")
  return "\n".join(parts)


class SynthesisNode(BaseAgentNode[SecondBrainState, SynthesisNodeOutput]):
  """Generates a final answer with confidence scoring."""

  def __init__(self):
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.SONNET))
    self._structured_llm = self._agent.get_model().with_structured_output(
      _SynthesisOutput
    )

  @override
  async def __call__(self, state: SecondBrainState) -> SynthesisNodeOutput:
    query = get_str_content(state["messages"][-1])
    routing = state.get("routing_decision", "neither")

    # Build context sections
    chunks: list[str] = []
    rag_context = ""
    if state.get("rag_results"):
      chunks = [r["content"] for r in state["rag_results"]]
      rag_context = "### RAG Context\n" + "\n---\n".join(chunks)

    items: list[str] = []
    web_context = ""
    if state.get("web_results"):
      items = [
        f"**{r['title']}** ({r['url']})\n{r['content']}" for r in state["web_results"]
      ]
      web_context = "### Web Research\n" + "\n---\n".join(items)

    facts: list[str] = []
    memory_context = ""
    if state.get("retrieved_memory"):
      facts = [
        f"- {m['fact']} (confidence: {m['confidence']:.2f})"
        for m in state["retrieved_memory"]
      ]
      memory_context = "### Memory\n" + "\n".join(facts)

    context_used = chunks + items + facts

    # Use only the last 10 messages (excluding the current query) for history
    conversation_history = _format_messages(state["messages"][-11:-1])

    context_parts = [p for p in [rag_context, web_context, memory_context] if p]
    no_context = "No additional context available."
    context_section = "\n\n".join(context_parts) if context_parts else no_context

    prior_conv = (
      conversation_history if conversation_history else "No prior conversation."
    )
    prompt = (
      "You are a knowledgeable Second Brain assistant. "
      "Synthesize a clear, accurate answer.\n\n"
      f"## Current Query\n{query}\n\n"
      f"## Available Context\n{context_section}\n\n"
      f"## Conversation History\n{prior_conv}\n\n"
      "## Instructions\n"
      "- Provide a direct, helpful answer to the query.\n"
      "- Rate your confidence (0.0-1.0) based on available evidence.\n"
      "- Explain your reasoning briefly.\n"
      "- If context is limited, say so honestly and keep confidence lower.\n"
    )

    output: _SynthesisOutput = await self._structured_llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]

    confidence = output.confidence
    # Floor confidence for conversational queries: skipping external retrieval
    # means no uncertain sources were consulted
    if routing == "neither":
      confidence = max(confidence, _NEITHER_CONFIDENCE_FLOOR)

    is_uncertain = confidence < _UNCERTAINTY_THRESHOLD
    return {
      "final_answer": output.final_answer,
      "confidence": confidence,
      "is_uncertain": is_uncertain,
      "context_used": context_used,
      # ponytail: awaiting_correction is set by memory_persistence_node, not here
    }


synthesize_answer = SynthesisNode()
```

- [ ] **Step 2: Update the test file's patch targets**

In `apps/backend/tests/unit/test_nodes/test_synthesis.py`, replace every occurrence of:

```python
  with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
```

with:

```python
  with patch("second_brain.nodes.synthesis.synthesize_answer._structured_llm") as mock_llm:
```

This occurs 11 times (lines 68, 107, 135, 159, 185, 231, 270, 293, 321, 358, 382 in the current file). No other lines in this file change — `_format_messages` is imported and called exactly as before.

- [ ] **Step 3: Run the test file, confirm PASS**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_synthesis.py -v`
Expected: 11 passed, 0 failed.

- [ ] **Step 4: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/synthesis.py apps/backend/tests/unit/test_nodes/test_synthesis.py
git commit -m "refactor: convert synthesis node to BaseAgentNode on ClaudeAgent"
```

### Acceptance Criteria

- 11 tests in `test_synthesis.py` pass.
- `just lint && just type-check` clean.
- Model string drift fixed: `"claude-sonnet-4-6"` -> `CLAUDE_MODEL_NAME.SONNET`.

## Attempt 1

### Implementation Plan
- Replaced full contents of `apps/backend/src/second_brain/nodes/synthesis.py` with the
  exact source given in the plan (SynthesisNode class on BaseAgentNode[SecondBrainState,
  SynthesisNodeOutput], using ClaudeAgent(CLAUDE_MODEL_NAME.SONNET), `_structured_llm`
  instance attribute, `_format_messages` stays module-level, `synthesize_answer =
  SynthesisNode()` module-level singleton). This also removes the stale hardcoded
  `"claude-sonnet-4-6"` model string (now resolved via ClaudeAgent/CLAUDE_MODEL_NAME.SONNET).
- Replaced all 11 occurrences of
  `patch("second_brain.nodes.synthesis._structured_llm")` with
  `patch("second_brain.nodes.synthesis.synthesize_answer._structured_llm")` in
  `apps/backend/tests/unit/test_nodes/test_synthesis.py` via `sed`.
- Ran `just format` to rewrap the resulting >88-char patch lines onto multiple lines
  (matches the established multi-line `with patch(\n  "..."\n) as mock_x:` style used
  in test_ingestion_agent.py, test_memory_retrieval.py, test_pii_redaction.py,
  test_rag_retrieval.py).

### Files Changed
- `apps/backend/src/second_brain/nodes/synthesis.py` (full replacement per plan)
- `apps/backend/tests/unit/test_nodes/test_synthesis.py` (11 patch-target edits +
  ruff-format line wrapping)

### New Tests
None — structural move covered by existing test suite (per plan; no new coverage needed).

### Key Decisions
- Needed `uv sync --all-extras` first since worktree venv lacked pytest — this is
  environment setup only, not a lockfile edit; no dependency was added/changed.
- After the sed replacement, 4 of the 11 patch lines exceeded 88 chars (ruff E501).
  Rather than hand-wrapping, ran `just format` (`ruff format .`) which auto-wrapped
  them to match the pre-existing multi-line `with patch(\n  "..."\n) as mock:` style
  used elsewhere in the test suite — 1 file reformatted, 108 unchanged, no semantic
  change.

### Lint Output
```
$ just lint
All checks passed!
```

### Type-check Output
```
$ just type-check
...
0 errors, 0 warnings, 8 notes
✅ Type check is completed
```
(8 informational notes are pre-existing, in unrelated files memory_persistence.py /
memory_retrieval.py — not introduced by this change.)

### Test Output
```
$ uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_synthesis.py -v
...
13 passed, 1 warning in 0.20s
```
(Plan said "11 passed" referring to the 11 patched tests; file has 13 tests total,
all pass, 0 failed — 2 tests don't touch `_structured_llm` and were unaffected by the
patch-target rename.)

### Commit
`refactor: convert synthesis node to BaseAgentNode on ClaudeAgent`

### Outcome
PASS on attempt 1.
