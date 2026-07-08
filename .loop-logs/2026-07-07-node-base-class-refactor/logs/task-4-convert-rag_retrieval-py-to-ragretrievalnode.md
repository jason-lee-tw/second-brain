# Task 4 Log: Convert rag_retrieval.py

## Task Context

- TASK_ID: task-4-convert-rag_retrieval-py-to-ragretrievalnode
- Worktree: .worktrees/task-4-convert-rag_retrieval-py-to-ragretrievalnode
- Branch: worktree/task-4-convert-rag_retrieval-py-to-ragretrievalnode (from HEAD 221ac94, includes Task 1 BaseNode/BaseAgentNode fix)

### Plan Section

### Task 4: Convert `rag_retrieval.py` to `RagRetrievalNode`

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/rag_retrieval.py`
- Test (no edits expected): `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py`

**Interfaces:**
- Produces: `retrieve_from_rag` (instance of `RagRetrievalNode`, `async def __call__`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/rag_retrieval.py`:

```python
"""RAG retrieval node: embeds the user query and fetches top-k chunks via pgvector."""

from typing import override

import httpx

from second_brain.config import settings
from second_brain.db.pool import get_pgvector_pool
from second_brain.graphs.state import RagResult, RagRetrievalOutput, SecondBrainState
from second_brain.nodes.base_node import BaseNode
from second_brain.services.chunking import ChunkMetadata
from second_brain.utils import get_str_content


def _row_to_chunk_metadata(row_meta: object) -> ChunkMetadata:
  # asyncpg.Record has no stubs; dict() triggers 3 pyright codes, same root cause
  d: dict[str, object] = dict(row_meta)  # pyright: ignore[reportCallIssue, reportAssignmentType, reportArgumentType]
  return {
    "source": str(d["source"]),
    "heading_path": str(d["heading_path"]),
    "content_type": str(d["content_type"]),
    "char_count": int(d["char_count"]),  # pyright: ignore[reportArgumentType]
  }


async def _embed_query(query: str, base_url: str) -> list[float]:
  """Call the local Ollama embedding endpoint and return the embedding vector."""
  async with httpx.AsyncClient() as client:
    resp = await client.post(
      f"{base_url}/api/embeddings",
      json={"model": "qwen3-embedding:0.6b", "prompt": query},
      timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


async def _query_pgvector(embedding: list[float], top_k: int = 5) -> list[RagResult]:
  """Query the document_chunks table for the top-k most similar chunks."""
  pool = await get_pgvector_pool()
  async with pool.acquire() as conn:
    rows = await conn.fetch(
      "SELECT content, 1-(embedding<=>$1) AS score, chunk_index, metadata"
      " FROM document_chunks"
      " ORDER BY embedding<=>$1"
      " LIMIT $2",
      embedding,
      top_k,
    )
    return [
      {
        "content": r["content"],
        "score": float(r["score"]),  # pyright: ignore[reportUnknownArgumentType]
        "chunk_index": r["chunk_index"],
        "metadata": (
          _row_to_chunk_metadata(r["metadata"])  # pyright: ignore[reportUnknownArgumentType]
          if r["metadata"]
          else None
        ),
      }
      for r in rows
    ]


class RagRetrievalNode(BaseNode[SecondBrainState, RagRetrievalOutput]):
  """Retrieves relevant chunks for the latest user message."""

  @override
  async def __call__(self, state: SecondBrainState) -> RagRetrievalOutput:
    query = get_str_content(state["messages"][-1])
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding)
    return {"rag_results": rows}


retrieve_from_rag = RagRetrievalNode()
```

- [ ] **Step 2: Run the existing test file to confirm still green**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_rag_retrieval.py -v`
Expected: all tests pass (patches target `_embed_query`/`_query_pgvector`, still module-level functions).

- [ ] **Step 3: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/second_brain/nodes/rag_retrieval.py
git commit -m "refactor: convert rag_retrieval node to BaseNode subclass"
```

### Acceptance Criteria

None listed beyond the Interfaces contract above (produces `retrieve_from_rag` as an instance of `RagRetrievalNode` with `async def __call__`).

## Attempt 1

**Implementation Plan:** Replace `apps/backend/src/second_brain/nodes/rag_retrieval.py` verbatim with the plan's Step 1 contents (converts module-level `retrieve_from_rag` async function into `RagRetrievalNode(BaseNode[SecondBrainState, RagRetrievalOutput])` with `async def __call__`, keeping `_row_to_chunk_metadata`, `_embed_query`, `_query_pgvector` as module-level helpers unchanged; instantiate `retrieve_from_rag = RagRetrievalNode()` at module scope).

**Files Changed:**
- `apps/backend/src/second_brain/nodes/rag_retrieval.py` (15 insertions, 6 deletions)

**New Tests:** none (existing `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py` covers this; not modified, per task spec).

**Key Decisions:**
- Confirmed `second_brain.nodes.base_node` resolves as a package (`base_node/__init__.py` re-exports `BaseNode` from `base_node/base_node.py`, plus `BaseAgentNode`) — Task 1's fix already merged into this worktree's base (branched from HEAD `221ac94`). No changes needed to import path.
- Ran `uv sync --all-extras` first since the fresh worktree's `.venv` only had `second-brain` built, missing `pytest`/dev deps.

**Lint Output:**
```
All checks passed!
```

**Type-check Output:**
```
0 errors, 0 warnings, 8 notes
✅ Type check is completed
```
(The 8 informational notes are pre-existing `reportUnknownArgumentType` notes in `memory_persistence.py` and `memory_retrieval.py` — unrelated files being edited concurrently by sibling worktree tasks, not touched by this task.)

**Test Output:**
```
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_retrieve_from_rag_happy_path PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_retrieve_from_rag_empty_results PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_retrieve_from_rag_uses_last_message PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_query_pgvector_uses_pool_acquire PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_query_pgvector_empty_metadata_returns_none PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_row_to_chunk_metadata_happy_path PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_row_to_chunk_metadata_missing_field PASSED
apps/backend/tests/unit/test_nodes/test_rag_retrieval.py::test_row_to_chunk_metadata_char_count_none PASSED
======================== 8 passed, 1 warning in 13.30s =========================
```

**Commit:** `555ab52` — "refactor: convert rag_retrieval node to BaseNode subclass" (pre-commit hook re-ran lint + type-check, both clean; commit-msg hook validated Conventional Commits format)

**Outcome:** PASS — task complete on attempt 1.

