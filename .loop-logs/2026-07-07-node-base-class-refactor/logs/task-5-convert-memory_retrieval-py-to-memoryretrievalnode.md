# Task 5 Log: Convert memory_retrieval.py

## Task Context

- Task ID: task-5-convert-memory_retrieval-py-to-memoryretrievalnode
- Worktree: `.worktrees/task-5-convert-memory_retrieval-py-to-memoryretrievalnode` (branch `worktree/task-5-convert-memory_retrieval-py-to-memoryretrievalnode`), branched from current HEAD (`221ac94 fix: correct BaseNode/BaseAgentNode call contract, export model name`), so Task 1's `BaseNode`/`BaseAgentNode` fix is already present.
- Plan: `docs/superpowers/plans/2026-07-07-node-base-class-refactor.md`
- Spec (context only): `docs/superpowers/specs/2026-07-07-node-base-class-refactor-design.md`

### Plan Section (verbatim)

### Task 5: Convert `memory_retrieval.py` to `MemoryRetrievalNode`

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/memory_retrieval.py`
- Test (no edits expected): `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py`

**Interfaces:**
- Produces: `memory_retrieval_node` (instance of `MemoryRetrievalNode`, `async def __call__`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/memory_retrieval.py`:

```python
"""MemoryRetrievalNode: dual-table cosine search.

Searches learned_facts + model_corrections tables.
"""

import asyncio
from typing import override

import asyncpg

from second_brain.config import settings
from second_brain.db.pool import get_pgvector_pool
from second_brain.graphs.state import MemoryItem, RetrieveMemoryOutput, SecondBrainState
from second_brain.nodes.base_node import BaseNode
from second_brain.services.embeddings import embed_text
from second_brain.utils import get_str_content, last_human_message


async def _search_facts(
  pool: asyncpg.Pool, embedding: list[float]
) -> list[tuple[float, MemoryItem]]:
  max_distance = 1 - settings.memory_retrieval_threshold
  async with pool.acquire() as conn:
    rows = await conn.fetch(
      "SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score"
      " FROM learned_facts"
      " WHERE (embedding<=>$1) < $2"
      " ORDER BY embedding<=>$1 ASC LIMIT 5",
      embedding,
      max_distance,
    )
    return [
      (
        float(r["score"]),
        MemoryItem(
          id=r["id"],
          fact=r["fact"],
          confidence=r["confidence"],
          type="learned_fact",
        ),
      )
      for r in rows
    ]


async def _search_corrections(
  pool: asyncpg.Pool, embedding: list[float]
) -> list[tuple[float, MemoryItem]]:
  max_distance = 1 - settings.memory_retrieval_threshold
  async with pool.acquire() as conn:
    rows = await conn.fetch(
      "SELECT id::text, correction AS fact, 1-(embedding<=>$1) AS score"
      " FROM model_corrections"
      " WHERE (embedding<=>$1) < $2"
      " ORDER BY embedding<=>$1 ASC LIMIT 3",
      embedding,
      max_distance,
    )
    return [
      (
        float(r["score"]),
        MemoryItem(
          id=r["id"],
          fact=r["fact"],
          confidence=1.0,
          type="model_correction",
        ),
      )
      for r in rows
    ]


class MemoryRetrievalNode(BaseNode[SecondBrainState, RetrieveMemoryOutput]):
  """Embed current query and run two parallel cosine searches.

  Fails hard on Ollama unavailability — no empty-list fallback.
  """

  @override
  async def __call__(self, state: SecondBrainState) -> RetrieveMemoryOutput:
    last_human = last_human_message(state["messages"])
    if last_human is None:
      return {"retrieved_memory": []}

    query_text = get_str_content(last_human)
    embedding = await embed_text(query_text)  # raises if Ollama is down

    pool = await get_pgvector_pool()
    facts_scored, corrections_scored = await asyncio.gather(
      _search_facts(pool, embedding),
      _search_corrections(pool, embedding),
    )

    all_scored = sorted(
      facts_scored + corrections_scored, key=lambda x: x[0], reverse=True
    )
    return {"retrieved_memory": [item for _, item in all_scored]}


memory_retrieval_node = MemoryRetrievalNode()
```

- [ ] **Step 2: Run the existing test file to confirm still green**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_memory_retrieval.py -v`
Expected: all tests pass (patches target `embed_text`/`get_pgvector_pool`, still module-level).

- [ ] **Step 3: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_retrieval.py
git commit -m "refactor: convert memory_retrieval node to BaseNode subclass"
```

### Acceptance Criteria

None additional beyond the plan steps above (pure structural move; existing test file covers behavior, no test edits expected).

## Attempt 1

### Implementation Plan

Apply the plan's exact full-file replacement to `apps/backend/src/second_brain/nodes/memory_retrieval.py`: convert the module-level `memory_retrieval_node` async function into a `MemoryRetrievalNode(BaseNode[SecondBrainState, RetrieveMemoryOutput])` class with `@override async def __call__`, keep the two module-level helper functions (`_search_facts`, `_search_corrections`) unchanged, and instantiate `memory_retrieval_node = MemoryRetrievalNode()` at module scope so the existing test file's target (`second_brain.nodes.memory_retrieval.memory_retrieval_node`, called as `await memory_retrieval_node(state)`) keeps working unchanged. First run needed `uv sync --all-extras` in the fresh worktree venv since `pytest` was not yet installed.

### Files Changed

- `apps/backend/src/second_brain/nodes/memory_retrieval.py` (26 insertions, 18 deletions) — converted to `MemoryRetrievalNode` class subclassing `BaseNode[SecondBrainState, RetrieveMemoryOutput]` from `second_brain.nodes.base_node`, added `from typing import override`, kept helper functions and business logic identical, added `memory_retrieval_node = MemoryRetrievalNode()` instance at bottom.

### New Tests (none)

No test file edits — per plan, `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py` targets `memory_retrieval_node` and calls it as `await memory_retrieval_node(state)`, which is unchanged behavior for a callable instance vs. a plain async function.

### Key Decisions

- Worktree branched from current HEAD (`221ac94`), so Task 1's `BaseNode`/`BaseAgentNode` package (`second_brain/nodes/base_node/` with `__init__.py` exporting `BaseNode`, `BaseAgentNode`) was already present — no need to pull it in separately.
- `uv sync --all-extras` was required once in this fresh worktree venv (pytest binary wasn't present) before `uv run --package second-brain pytest ...` would work; this is a worktree environment-setup step, not a task-plan deviation.

### Lint Output

`just lint` → `All checks passed!`
`just type-check` → `0 errors, 0 warnings, 8 notes` (all 8 notes are pre-existing informational `reportUnknownArgumentType` notes on `MemoryItem(...)` calls stemming from `asyncpg.Record.__getitem__` returning `Any`; identical pattern also present in untouched `memory_persistence.py`, not introduced by this change).

### Test Output

```
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_merges_and_sorts_by_score PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_returns_empty_when_db_empty PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_uses_last_human_message_by_type PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_fails_hard_when_embed_raises PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_threshold_applied_to_sql_queries PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_threshold_binds_precomputed_max_distance_not_raw_threshold PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_threshold_excludes_low_similarity_corrections PASSED
apps/backend/tests/unit/test_nodes/test_memory_retrieval.py::test_threshold_allows_high_similarity_results PASSED
========================= 8 passed, 1 warning in 3.27s =========================
```

### Commit

`3e0e289bdb27d4dcd35e40b7099ff02e0d456cbb` — `refactor: convert memory_retrieval node to BaseNode subclass` (pre-commit hooks: format/lint/type-check/commit-msg all passed automatically).

### Outcome

PASS on attempt 1.
