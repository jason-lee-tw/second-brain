# Task 6 Log: Convert memory_persistence.py

## Task Context

- Task ID: task-6-convert-memory_persistence-py-to-memorypersistencenode
- Worktree: .worktrees/task-6-convert-memory_persistence-py-to-memorypersistencenode
- Branch: worktree/task-6-convert-memory_persistence-py-to-memorypersistencenode (branched from HEAD, which already has Task 1's BaseNode/BaseAgentNode fix merged)

### Plan Section

### Task 6: Convert `memory_persistence.py` to `MemoryPersistenceNode`

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/memory_persistence.py`
- Test (no edits expected): `apps/backend/tests/unit/test_nodes/test_memory_persistence.py`

**Interfaces:**
- Produces: `memory_persistence_node` (instance of `MemoryPersistenceNode`, `async def __call__`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/memory_persistence.py`:

```python
"""MemoryPersistenceNode: writes facts and corrections to the database.

Conflict-check reads: asyncpg pool (get_pgvector_pool)
Writes: SQLModel sync Session(engine) wrapped in asyncio.to_thread
Per-fact retry: up to _MAX_RETRIES attempts before raising
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, override

from sqlmodel import Session

from second_brain.config import settings
from second_brain.db.models import LearnedFact, ModelCorrection
from second_brain.db.pool import get_pgvector_pool
from second_brain.db.session import engine
from second_brain.graphs.state import CorrectionUpdate, FactUpdate, SecondBrainState
from second_brain.nodes.base_node import BaseNode
from second_brain.services.embeddings import embed_text

logger = logging.getLogger(__name__)
_MAX_RETRIES = 3


async def _conflict_check(embedding: list[float]) -> list[dict[str, Any]]:
  """Return rows from learned_facts whose cosine similarity exceeds threshold."""
  threshold = settings.memory_conflict_threshold
  max_distance = 1 - threshold
  pool = await get_pgvector_pool()
  async with pool.acquire() as conn:
    rows = await conn.fetch(
      "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
      " FROM learned_facts"
      " WHERE (embedding<=>$1) < $2"
      " ORDER BY embedding<=>$1 ASC LIMIT 5",
      embedding,
      max_distance,
    )
    return [dict(r) for r in rows]


def _retry_write(fn: Any, *args: Any) -> None:
  """Run a sync write function with up to _MAX_RETRIES attempts, then raise."""
  for attempt in range(_MAX_RETRIES):
    try:
      fn(*args)
      return
    except Exception as exc:
      logger.warning(
        "memory write attempt %d/%d failed: %s",
        attempt + 1,
        _MAX_RETRIES,
        exc,
        exc_info=True,
      )
      if attempt == _MAX_RETRIES - 1:
        raise


def _write_fact(
  fact_update: FactUpdate,
  session_id: str,
  embedding: list[float],
) -> None:
  with Session(engine) as session:
    # Delete replaced facts first (conflict resolution path)
    for cid in fact_update.get("conflicts_with") or []:
      row = session.get(LearnedFact, uuid.UUID(cid))
      if row:
        session.delete(row)
    session.add(
      LearnedFact(
        id=uuid.uuid4(),
        fact=fact_update["fact"],
        embedding=embedding,
        source_session=session_id,
        confidence=fact_update["confidence"],
      )
    )
    session.commit()


def _write_correction(
  correction: CorrectionUpdate,
  session_id: str,
  embedding: list[float],
) -> None:
  with Session(engine) as session:
    session.add(
      ModelCorrection(
        id=uuid.uuid4(),
        original_answer=correction["original_answer"],
        correction=correction["correction"],
        root_cause=correction["root_cause"],
        embedding=embedding,
        source_session=session_id,
      )
    )
    session.commit()


async def _persist_fact(
  fact_update: FactUpdate,
  session_id: str,
  skip_conflict_check: bool = False,
) -> dict[str, Any] | None:
  """Persist one fact. Returns conflict dict on conflict, None on success.

  skip_conflict_check should be True when the caller is already in a
  conflict-resolution turn (awaiting_conflict_clarification=True).  This
  prevents _conflict_check from firing again when the LLM omitted the
  conflicts_with UUID, which would otherwise cause an infinite loop (F1).
  """
  embedding = await embed_text(fact_update["fact"])

  # conflicts_with non-empty → user resolved conflict; delete old facts then write.
  # skip_conflict_check → conflict was already handled last turn; write directly
  # even if the LLM omitted the UUID (prevents re-entering conflict state, F1 fix).
  if fact_update.get("conflicts_with") or skip_conflict_check:
    await asyncio.to_thread(
      _retry_write, _write_fact, fact_update, session_id, embedding
    )
    return None

  conflicts = await _conflict_check(embedding)
  if conflicts:
    return {
      "existing": conflicts[0]["fact"],
      "existing_id": conflicts[0]["id"],
      "new": fact_update["fact"],
    }

  await asyncio.to_thread(_retry_write, _write_fact, fact_update, session_id, embedding)
  return None


class MemoryPersistenceNode(BaseNode[SecondBrainState, dict[str, Any]]):
  """Tool-call node: embeds and persists fact_updates + correction_updates."""

  @override
  async def __call__(self, state: SecondBrainState) -> dict[str, Any]:
    fact_updates: list[FactUpdate] = state.get("fact_updates") or []
    correction_updates: list[CorrectionUpdate] = state.get("correction_updates") or []
    session_id: str = state["session_id"]
    final_answer: str = state.get("final_answer", "")

    # F1 fix: if we are resolving a conflict from a prior turn, skip _conflict_check
    # even when the LLM omits conflicts_with — prevents re-entering conflict state.
    coming_from_conflict: bool = state.get("awaiting_conflict_clarification", False)  # type: ignore[union-attr]

    conflict_contexts: list[dict[str, Any]] = []
    pending_facts: list[dict[str, Any]] = []

    for fact_update in fact_updates:
      conflict = await _persist_fact(
        fact_update, session_id, skip_conflict_check=coming_from_conflict
      )
      if conflict is not None:
        conflict_contexts.append(conflict)
        pending_facts.append(
          {
            "fact": fact_update["fact"],
            "confidence": fact_update["confidence"],
            "conflicts_with": [conflict["existing_id"]],
          }
        )

    for correction in correction_updates:
      embedding = await embed_text(correction["correction"])
      await asyncio.to_thread(
        _retry_write, _write_correction, correction, session_id, embedding
      )

    # Set awaiting_correction AFTER memory_agent so the flag is available in the
    # NEXT turn's memory_agent (cross-turn correction detection).
    result: dict[str, Any] = {
      "awaiting_correction": state.get("is_uncertain", False),
      "awaiting_conflict_clarification": bool(conflict_contexts),
      "conflict_context": conflict_contexts,
      "fact_updates": pending_facts if conflict_contexts else [],
      "correction_updates": [],
    }

    if conflict_contexts:
      conflict_msg = "\n\n⚠️ I noticed potential conflicts with existing memory:\n"
      for c in conflict_contexts:
        conflict_msg += f'- Existing: "{c["existing"]}" | New: "{c["new"]}"\n'
      conflict_msg += "Please clarify which is correct (or if both apply)."
      result["final_answer"] = final_answer + conflict_msg

    return result


memory_persistence_node = MemoryPersistenceNode()
```

- [ ] **Step 2: Run the existing test file to confirm still green**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_memory_persistence.py -v`
Expected: all tests pass (patches target `embed_text`/`get_pgvector_pool`/`Session`, still module-level).

- [ ] **Step 3: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_persistence.py
git commit -m "refactor: convert memory_persistence node to BaseNode subclass"
```

### Acceptance Criteria

- `memory_persistence_node` becomes an instance of `MemoryPersistenceNode(BaseNode[SecondBrainState, dict[str, Any]])` with `async def __call__`.
- Existing test file `test_memory_persistence.py` passes unmodified.
- `just lint` and `just type-check` clean.

## Attempt 1

### Implementation Plan
Apply the exact plan-specified full-file replacement to `apps/backend/src/second_brain/nodes/memory_persistence.py`:
converted `async def memory_persistence_node(...)` into `class MemoryPersistenceNode(BaseNode[SecondBrainState, dict[str, Any]])`
with `@override async def __call__`, imported `override` from `typing` and `BaseNode` from `second_brain.nodes.base_node`,
and instantiated `memory_persistence_node = MemoryPersistenceNode()` at module bottom. No other logic changed.

### Files Changed
- `apps/backend/src/second_brain/nodes/memory_persistence.py` (1 file changed, 53 insertions(+), 46 deletions(-))

### New Tests
None (existing test file `apps/backend/tests/unit/test_nodes/test_memory_persistence.py` covers this node and required no edits).

### Key Decisions
- Applied the plan's exact replacement text verbatim (structural class-wrap only); no behavioral changes.
- Kept all helper functions (`_conflict_check`, `_retry_write`, `_write_fact`, `_write_correction`, `_persist_fact`) at module scope unchanged.

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
(8 informational notes are pre-existing `reportUnknownArgumentType` notes in `memory_persistence.py` and `memory_retrieval.py`, unrelated to this change — 0 errors/warnings.)

### Test Output
```
$ uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_memory_persistence.py -v
...
9 passed, 1 warning in 20.53s
```

### Commit
```
git add apps/backend/src/second_brain/nodes/memory_persistence.py
git commit -m "refactor: convert memory_persistence node to BaseNode subclass"
```
Commit: 01a7c6c (branch worktree/task-6-convert-memory_persistence-py-to-memorypersistencenode)
Pre-commit hooks (lint, type-check, commit-msg format) passed.

### Outcome
PASS — all 9 tests green, lint clean, type-check clean, commit created successfully on attempt 1.
