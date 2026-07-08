# Task 1 Log: Fix BaseAgentNode annotation bug, fix __call__ return-type contract, export CLAUDE_MODEL_NAME

## Task Context

### Plan Section

### Task 1: Fix `BaseAgentNode` annotation bug, fix `__call__` return-type contract, export `CLAUDE_MODEL_NAME`

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`
- Modify: `apps/backend/src/second_brain/nodes/base_node/base_node.py`
- Modify: `apps/backend/src/second_brain/nodes/base_node/agents/__init__.py`

**Interfaces:**
- Produces: `second_brain.nodes.base_node.agents.CLAUDE_MODEL_NAME` importable alongside `ClaudeAgent`/`BaseAgent` — every later task (8–11) imports it this way: `from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent`.
- Produces: both `BaseNode.__call__` and `BaseAgentNode.__call__` typed to return `Awaitable[ResultStateType] | ResultStateType` — every concrete subclass in Tasks 2–11 (sync or async) satisfies this signature and must add `@override`.

This task also fixes a return-type contract bug, verified live against this repo's basedpyright config: the abstract `__call__` on both base classes is declared sync-only, so every planned `async def __call__` override (8 of 11 subclasses across Tasks 3–6, 8–11) fails `just type-check` with a hard `reportIncompatibleMethodOverride` error, and every override without `@override` (all 11) fails it with `reportImplicitOverride` — a warning, but `just type-check`'s exit code still fails on it. Fixing the return type to a union and adding `@override` everywhere keeps the real override-safety check active instead of suppressing it project-wide. There's no new business-logic behavior, so there's no new test to write beyond the existing full suite.

- [ ] **Step 1: Fix the `_agent` annotation and `__call__` return type on `BaseAgentNode`**

Replace the full contents of `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`:

```python
from abc import ABC, abstractmethod
from collections.abc import Awaitable

from .agents import BaseAgent


class BaseAgentNode[InputStateType, ResultStateType](ABC):
  _agent: BaseAgent

  def __init__(self, agent: BaseAgent):
    super().__init__()
    self._agent = agent

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
```

- [ ] **Step 2: Fix the `__call__` return type on `BaseNode`**

Replace the full contents of `apps/backend/src/second_brain/nodes/base_node/base_node.py`:

```python
from abc import ABC, abstractmethod
from collections.abc import Awaitable

type ResponseStateType = object


class BaseNode[InputStateType, ResultStateType](ABC):
  def __init__(self):
    super().__init__()

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
```

- [ ] **Step 3: Export `CLAUDE_MODEL_NAME`**

Replace the full contents of `apps/backend/src/second_brain/nodes/base_node/agents/__init__.py`:

```python
from .base_agent import BaseAgent
from .claude_agent import CLAUDE_MODEL_NAME, ClaudeAgent

__all__ = ["BaseAgent", "CLAUDE_MODEL_NAME", "ClaudeAgent"]
```

- [ ] **Step 4: Run verification**

Run: `just lint && just type-check && just test-unit`
Expected: all pass with no errors (there are no existing `BaseNode`/`BaseAgentNode` subclasses in the codebase yet, so the return-type widening and `_agent` annotation change are both invisible at runtime and at every current call site).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/base_node/base_agent_node.py apps/backend/src/second_brain/nodes/base_node/base_node.py apps/backend/src/second_brain/nodes/base_node/agents/__init__.py
git commit -m "fix: correct BaseNode/BaseAgentNode __call__ contract (annotation + async-compatible return type), export CLAUDE_MODEL_NAME"
```

### Acceptance Criteria
- AC-1: `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py` has `_agent: BaseAgent` annotation (not `_agent = BaseAgent`) and `__call__` returns `Awaitable[ResultStateType] | ResultStateType`.
- AC-2: `apps/backend/src/second_brain/nodes/base_node/base_node.py`'s `__call__` returns `Awaitable[ResultStateType] | ResultStateType`.
- AC-3: `second_brain.nodes.base_node.agents.CLAUDE_MODEL_NAME` is importable alongside `ClaudeAgent`/`BaseAgent`.
- AC-4: `just lint && just type-check && just test-unit` all pass with no errors.

## Attempt 1 — 2026-07-07T06:53:20Z

### Implementation Plan
- Replace `base_agent_node.py`: fix `_agent = BaseAgent` → `_agent: BaseAgent` annotation, widen `__call__` return type to `Awaitable[ResultStateType] | ResultStateType`.
- Replace `base_node.py`: widen `__call__` return type to `Awaitable[ResultStateType] | ResultStateType`.
- Replace `agents/__init__.py`: export `CLAUDE_MODEL_NAME` alongside `BaseAgent`/`ClaudeAgent`.
- Run `just lint && just type-check && just test-unit`, commit if all green.

### Files Changed
- modified `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py` — fixed dead `_agent` class attribute into a type annotation; widened `__call__` return type
- modified `apps/backend/src/second_brain/nodes/base_node/base_node.py` — widened `__call__` return type to support async overrides
- modified `apps/backend/src/second_brain/nodes/base_node/agents/__init__.py` — added `CLAUDE_MODEL_NAME` to imports and `__all__`

### New Tests
(none — pure structural/type fix; no existing `BaseNode`/`BaseAgentNode` subclasses yet, so no new test is warranted beyond the existing full suite per the plan)

### Key Decisions
- Commit subject in the plan text ("fix: correct BaseNode/BaseAgentNode __call__ contract (annotation + async-compatible return type), export CLAUDE_MODEL_NAME") is 123 chars and was rejected by the repo's `commit-msg` hook (limit 72 chars). Used a short Conventional Commits subject ("fix: correct BaseNode/BaseAgentNode call contract") with the full detail moved into the commit body instead, preserving intent without violating the hook.
- `just lint`/`just type-check` initially failed with "Failed to spawn: ruff" because the worktree had never run `just init` (fresh `.venv`) — ran `just init` once before verification; this is worktree setup, not a task-code change.

### Lint Output
PASS

### Test Output
PASS (210 passed, 0 new)

### Commit
`50c81da`

### Outcome: success
