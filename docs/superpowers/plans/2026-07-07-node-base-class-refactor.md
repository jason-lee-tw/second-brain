# Node Base-Class Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert every LangGraph node under `apps/backend/src/second_brain/nodes/` to extend `BaseNode` or `BaseAgentNode`, with each agent-based node owning its own `ClaudeAgent` internally so graphs never construct or name a model.

**Architecture:** In-place conversion — every node module keeps its file path and its current public symbol name (rebound from a function to a `__call__`-able class instance), so graph files need zero or near-zero edits. Helpers that don't touch `self` stay as module-level functions. Full rationale in `docs/superpowers/specs/2026-07-07-node-base-class-refactor-design.md`.

**Tech Stack:** Python 3.13, LangGraph, LangChain (`langchain-anthropic`), Pydantic, SQLModel/asyncpg, pytest + pytest-asyncio, basedpyright, ruff.

## Global Constraints

- Every task must leave `just lint`, `just format`, and `just type-check` clean, and `just test-unit` fully green (project `Done Means`).
- Commits follow Conventional Commits (enforced by `.hooks/commit-msg`).
- Do not suppress errors with broad excepts (existing broad-catch teardown paths in `main.py` are pre-existing and out of scope).
- No new dependencies.
- This is a **behavior-preserving structural refactor** with three explicitly approved exceptions (see spec decisions 3 and 6–8):
  1. `orchestrator`/`memory_agent`/`synthesis` move from an unset (`None`, ~1.0) temperature to `ClaudeAgent`'s default `temperature=0.7`.
  2. `ingestion_agent`'s header generation moves from the raw `anthropic.AsyncAnthropic` SDK client to `ClaudeAgent`/`ChatAnthropic`.
  3. `settings.ingestion_model` and `ingestion_agent.shutdown()` (plus its two call sites in `main.py`) are deleted.
  4. `orchestrator`/`memory_agent`/`ingestion_agent` move from the undated alias `"claude-haiku-4-5"` to the dated snapshot `CLAUDE_MODEL_NAME.HAIKU = "claude-haiku-4-5-20251001"` — accepted for reproducibility (a rolling alias can silently change model behavior underneath you without a code change).
- **Per-task verification cycle:** for tasks that are pure structural moves already covered by an existing passing test file, the cycle is *convert source → update test patch targets to match the new structure → run the test file → confirm PASS*, not a contrived red-green — the correctness spec already lives in the existing test. Where behavior genuinely changes (Task 11's header generation), a real failing-test-first cycle is used for that specific piece.
- Naming rule: every module's current public symbol (the name graphs/tests import) is rebound from a function to a singleton instance — the name itself never changes.
- Method rule: only helpers touching `self._agent`/a cached model become instance methods; everything else stays a module-level private function.

---

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

---

### Task 2: Convert `pii_redaction.py` to `RedactInboundNode` / `RedactOutboundNode`

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/pii_redaction.py`
- Test (no edits expected): `apps/backend/tests/unit/test_nodes/test_pii_redaction.py`

**Interfaces:**
- Consumes: `BaseNode` from `second_brain.nodes.base_node` (Task 1 unaffected — `BaseNode` already existed).
- Produces: `redact_inbound` (instance of `RedactInboundNode`, sync `__call__`), `redact_outbound` (instance of `RedactOutboundNode`, sync `__call__`) — same names, same sync call signature the existing tests already use (`redact_inbound(state)`, no `await`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/pii_redaction.py`:

```python
"""PII redaction graph nodes for inbound queries and outbound answers."""

from typing import override

from langchain_core.messages import HumanMessage

from second_brain.graphs.state import (
  RedactInboundOutput,
  RedactOutboundOutput,
  SecondBrainState,
)
from second_brain.nodes.base_node import BaseNode
from second_brain.services.pii import redact_pii
from second_brain.utils import get_str_content


class RedactInboundNode(BaseNode[SecondBrainState, RedactInboundOutput]):
  """Redact PII from the last message before it enters the graph."""

  @override
  def __call__(self, state: SecondBrainState) -> RedactInboundOutput:
    """Returns only the redacted message; the ``add_messages`` reducer replaces
    the existing message by id, preserving all prior messages.
    """
    if not state["messages"]:
      raise ValueError("redact_inbound requires at least one message in state")
    last = state["messages"][-1]
    redacted = HumanMessage(content=redact_pii(get_str_content(last)), id=last.id)
    return {"messages": [redacted]}


class RedactOutboundNode(BaseNode[SecondBrainState, RedactOutboundOutput]):
  """Redact PII from the final answer before it leaves the graph."""

  @override
  def __call__(self, state: SecondBrainState) -> RedactOutboundOutput:
    return {"final_answer": redact_pii(state["final_answer"])}


redact_inbound = RedactInboundNode()
redact_outbound = RedactOutboundNode()
```

- [ ] **Step 2: Run the existing test file to confirm still green**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_pii_redaction.py -v`
Expected: 6 passed, 0 failed (same tests, same behavior — only the object type behind `redact_inbound`/`redact_outbound` changed from function to instance).

- [ ] **Step 3: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/second_brain/nodes/pii_redaction.py
git commit -m "refactor: convert pii_redaction nodes to BaseNode subclasses"
```

---

### Task 3: Convert `web_research.py` to `WebResearchNode`

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/web_research.py`
- Test (no edits expected): `apps/backend/tests/unit/test_nodes/test_web_research.py`

**Interfaces:**
- Produces: `search_web` (instance of `WebResearchNode`, `async def __call__`).

- [ ] **Step 1: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/web_research.py`:

```python
"""Web Research node: queries Tavily search API."""

import asyncio
from typing import override

from tavily import TavilyClient

from second_brain.config import settings
from second_brain.graphs.state import SecondBrainState, WebResearchOutput, WebResult
from second_brain.nodes.base_node import BaseNode
from second_brain.utils import get_str_content


class WebResearchNode(BaseNode[SecondBrainState, WebResearchOutput]):
  """Search the web using Tavily and return up to 3 results."""

  @override
  async def __call__(self, state: SecondBrainState) -> WebResearchOutput:
    query = get_str_content(state["messages"][-1])
    client = TavilyClient(api_key=settings.tavily_api_key.get_secret_value())
    response = await asyncio.to_thread(lambda: client.search(query, max_results=3))  # pyright: ignore[reportUnknownLambdaType]
    web_results: list[WebResult] = [
      {
        "title": r.get("title", ""),
        "url": r.get("url", ""),
        "content": r.get("content", ""),
      }
      for r in response.get("results", [])
    ]
    return {"web_results": web_results}


search_web = WebResearchNode()
```

- [ ] **Step 2: Run the existing test file to confirm still green**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_web_research.py -v`
Expected: all tests pass (the `TavilyClient` patch target is unchanged — it's still a module-level import).

- [ ] **Step 3: Run lint/type-check**

Run: `just lint && just type-check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/second_brain/nodes/web_research.py
git commit -m "refactor: convert web_research node to BaseNode subclass"
```

---

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

---

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

---

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

---

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

---

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

---

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

---

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

---

### Task 11: Convert `ingestion_agent.py` to `IngestionAgentNode`, remove `shutdown()`, drop dead config

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/ingestion_agent.py`
- Modify: `apps/backend/src/second_brain/config.py`
- Modify: `apps/backend/src/second_brain/main.py`
- Modify: `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py`
- Modify: `apps/backend/tests/integration/test_ingestion_graph.py`

**Interfaces:**
- Consumes: `CLAUDE_MODEL_NAME`, `ClaudeAgent` (Task 1).
- Produces: `ingestion_agent_node` (instance of `IngestionAgentNode`, `async def __call__`), with a `_model` instance attribute (`ClaudeAgent(HAIKU).get_model()`, a plain `ChatAnthropic`, no structured output). `_generate_contextual_header` and `_process_one_chunk` and `_do_ingest` become instance methods (they call `self._model`/`self._generate_contextual_header`/`self._process_one_chunk`/`self._do_ingest` transitively); `_sync_check_duplicate` and `_sync_write_results` stay module-level (no `self` dependency).

This task has one piece of genuine behavior change — header generation moves off the raw `anthropic.AsyncAnthropic` SDK client onto `ClaudeAgent`/`ChatAnthropic` — so that specific test is written test-first (red, then green). The rest is a structural move verified by the existing suite.

- [ ] **Step 1: Write the new failing test for header generation**

In `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py`, delete the existing `test_generate_contextual_header_raises_when_no_text_block` test (lines 142–159):

```python
@pytest.mark.asyncio
async def test_generate_contextual_header_raises_when_no_text_block():
  """_generate_contextual_header raises ValueError when response has no TextBlock."""
  mock_response = MagicMock()
  mock_response.content = []  # no TextBlock

  with patch(
    "second_brain.nodes.ingestion_agent._anthropic.messages.create",
    new=AsyncMock(return_value=mock_response),
  ):
    from second_brain.nodes.ingestion_agent import _generate_contextual_header

    with pytest.raises(ValueError, match="No TextBlock in Anthropic response"):
      await _generate_contextual_header(
        filename="doc.md",
        heading_path="Intro",
        chunk_content="Some content here.",
      )
```

Replace it with this test, in the same location:

```python
@pytest.mark.asyncio
async def test_generate_contextual_header_strips_whitespace():
  """_generate_contextual_header strips leading/trailing whitespace from the LLM response."""
  from second_brain.nodes.ingestion_agent import ingestion_agent_node

  mock_response = MagicMock()
  mock_response.content = (
    "  This chunk is from doc.md, section Intro, covering testing.  "
  )

  with patch.object(
    ingestion_agent_node._model, "ainvoke", AsyncMock(return_value=mock_response)
  ):
    header = await ingestion_agent_node._generate_contextual_header(
      filename="doc.md",
      heading_path="Intro",
      chunk_content="Some content here.",
    )

  assert header == "This chunk is from doc.md, section Intro, covering testing."
```

- [ ] **Step 2: Run the new test to confirm it fails**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_ingestion_agent.py::test_generate_contextual_header_strips_whitespace -v`
Expected: FAIL — `ingestion_agent_node` is still the old plain async function, so `ingestion_agent_node._model` raises `AttributeError: 'function' object has no attribute '_model'`.

- [ ] **Step 3: Convert the module**

Replace the full contents of `apps/backend/src/second_brain/nodes/ingestion_agent.py`:

```python
import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import override

from sqlmodel import Session, select

from second_brain.config import settings
from second_brain.db.models import DocumentChunk, IngestedDocument
from second_brain.db.session import engine
from second_brain.graphs.state import FailedFile, IngestionAgentOutput, IngestionState
from second_brain.nodes.base_node import BaseAgentNode
from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent
from second_brain.services.chunking import Chunk, chunk_document
from second_brain.services.embeddings import embed_text

PENDING_DOCS_DIR = settings.pending_docs_dir
PROCESSED_DIR = Path("temp/processed")
FAILED_DIR = Path("temp/failed")

MAX_RETRIES = 3

_CHUNK_CONCURRENCY = 10
_CHUNK_SEMAPHORE = asyncio.Semaphore(_CHUNK_CONCURRENCY)


def _sync_check_duplicate(content_hash: str) -> bool:
  with Session(engine) as session:
    existing = session.exec(
      select(IngestedDocument).where(IngestedDocument.content_hash == content_hash)
    ).first()
    return existing is not None


def _sync_write_results(
  doc_id: uuid.UUID,
  filename: str,
  source_url: str | None,
  content_hash: str,
  doc_chunks: list[DocumentChunk],
) -> None:
  with Session(engine) as session:
    session.add(
      IngestedDocument(
        id=doc_id,
        filename=filename,
        source_url=source_url,
        content_hash=content_hash,
        status="processed",
        ingested_at=datetime.now(UTC),
      )
    )
    session.flush()
    for doc_chunk in doc_chunks:
      session.add(doc_chunk)
    session.commit()


class IngestionAgentNode(BaseAgentNode[IngestionState, IngestionAgentOutput]):
  """Process in_progress, update state on success or failure."""

  def __init__(self):
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU))
    self._model = self._agent.get_model()

  async def _generate_contextual_header(
    self, filename: str, heading_path: str, chunk_content: str
  ) -> str:
    """Generate a 50-100 token context header per chunk via claude-haiku-4-5."""
    prompt = (
      "Write a single-sentence context header (50-100 tokens) "
      "for this document chunk.\n"
      f"Document: {filename}\n"
      f"Section: {heading_path or 'N/A'}\n"
      f"Chunk preview: {chunk_content[:300]}\n\n"
      "Format exactly: "
      "'This chunk is from [filename], section [section], covering [brief topic].'\n"
      "Output only the header sentence, nothing else."
    )
    response = await self._model.ainvoke(prompt)
    return str(response.content).strip()

  async def _process_one_chunk(
    self, chunk: Chunk, filename: str, doc_id: uuid.UUID
  ) -> DocumentChunk:
    header = await self._generate_contextual_header(
      filename=filename,
      heading_path=chunk.metadata["heading_path"],
      chunk_content=chunk.content,
    )
    embedded_text = f"{header}\n\n{chunk.content}"
    embedding = await embed_text(embedded_text)
    return DocumentChunk(
      doc_id=doc_id,
      content=embedded_text,
      embedding=embedding,
      chunk_index=chunk.chunk_index,
      chunk_metadata=chunk.metadata,
    )

  async def _do_ingest(self, filename: str, source_url: str | None = None) -> None:
    """Read, chunk, embed, and store one markdown file."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    filepath = PENDING_DOCS_DIR / filename
    content = filepath.read_text(encoding="utf-8")
    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

    is_duplicate = await asyncio.to_thread(_sync_check_duplicate, content_hash)
    if is_duplicate:
      filepath.rename(PROCESSED_DIR / filename)
      return

    doc_id = uuid.uuid4()
    chunks = chunk_document(content, source=filename)

    async def _bounded(chunk: Chunk) -> DocumentChunk:
      async with _CHUNK_SEMAPHORE:
        return await self._process_one_chunk(chunk, filename, doc_id)

    doc_chunks = await asyncio.gather(*[_bounded(chunk) for chunk in chunks])

    await asyncio.to_thread(
      _sync_write_results,
      doc_id,
      filename,
      source_url,
      content_hash,
      list(doc_chunks),
    )

    filepath.rename(PROCESSED_DIR / filename)

  @override
  async def __call__(self, state: IngestionState) -> IngestionAgentOutput:
    """LangGraph node: process in_progress, update state on success or failure."""
    if state["in_progress"] is None:
      raise ValueError("ingestion_agent_node called with empty in_progress")

    filename = state["in_progress"]

    retry_item = next(
      (f for f in state["retry_queue"] if f["filename"] == filename), None
    )
    current_count: int = retry_item["retry_count"] if retry_item else 0
    new_retry_queue = [f for f in state["retry_queue"] if f["filename"] != filename]

    source_url = state.get("source_urls", {}).get(filename)

    try:
      await self._do_ingest(filename, source_url=source_url)

      return {
        "processed": state["processed"] + [filename],
        "in_progress": None,
        "retry_queue": new_retry_queue,
      }

    except Exception as exc:
      error_msg = str(exc)
      next_count = current_count + 1
      entry: FailedFile = {
        "filename": filename,
        "error": error_msg,
        "retry_count": next_count,
      }

      if next_count < MAX_RETRIES:
        return {
          "in_progress": None,
          "retry_queue": new_retry_queue + [entry],
          "failed": state["failed"],
        }

      FAILED_DIR.mkdir(parents=True, exist_ok=True)
      src = PENDING_DOCS_DIR / filename
      if src.exists():
        src.rename(FAILED_DIR / filename)
      return {
        "in_progress": None,
        "retry_queue": new_retry_queue,
        "failed": state["failed"] + [entry],
      }


ingestion_agent_node = IngestionAgentNode()
```

- [ ] **Step 4: Run the new test to confirm it passes**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_ingestion_agent.py::test_generate_contextual_header_strips_whitespace -v`
Expected: PASS.

- [ ] **Step 5: Update the remaining `_generate_contextual_header` patch targets in the unit test file**

In `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py`, replace every remaining occurrence of:

```python
    patch(
      "second_brain.nodes.ingestion_agent._generate_contextual_header",
      AsyncMock(return_value=fake_header),
    ),
```

(and the equivalent with `AsyncMock(return_value="header")`) with the same call but targeting `ingestion_agent.ingestion_agent_node._generate_contextual_header` — e.g.:

```python
    patch(
      "second_brain.nodes.ingestion_agent.ingestion_agent_node._generate_contextual_header",
      AsyncMock(return_value=fake_header),
    ),
```

This applies to the 3 remaining occurrences at (pre-edit) lines 49–52, 118–121, and 178–181. Everything else in this file (`PENDING_DOCS_DIR`, `PROCESSED_DIR`, `FAILED_DIR`, `Session`, `embed_text`, `_CHUNK_CONCURRENCY`, `_CHUNK_SEMAPHORE` patches) is unchanged — those stay module-level.

- [ ] **Step 6: Run the full unit test file, confirm PASS**

Run: `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_ingestion_agent.py -v`
Expected: 6 passed, 0 failed (5 original tests minus the removed one, plus the new one).

- [ ] **Step 7: Update the integration test file's patch targets**

In `apps/backend/tests/integration/test_ingestion_graph.py`, replace every occurrence of:

```python
    patch(
      f"{node}._generate_contextual_header",
      AsyncMock(return_value=FAKE_HEADER),
    ),
```

with:

```python
    patch(
      f"{node}.ingestion_agent_node._generate_contextual_header",
      AsyncMock(return_value=FAKE_HEADER),
    ),
```

This occurs 3 times (in `test_full_ingest_file_success`, `test_duplicate_file_is_skipped_on_reingest`, `test_api_endpoint_ingest_file_returns_correct_response`). `node = "second_brain.nodes.ingestion_agent"` stays defined as-is at the top of each test.

- [ ] **Step 8: Remove `shutdown()` from `main.py`**

In `apps/backend/src/second_brain/main.py`, remove line 12:

```python
from second_brain.nodes import ingestion_agent
```

and remove these lines (currently 35–38):

```python
  try:
    await ingestion_agent.shutdown()
  except Exception:
    _logger.warning("ingestion_agent.shutdown() raised an exception", exc_info=True)
```

The resulting `lifespan` function body (after the `embeddings.shutdown()` block) goes straight to the `shutdown_query_graph()` block:

```python
  try:
    await embeddings.shutdown()
  except Exception:
    _logger.warning("embeddings.shutdown() raised an exception", exc_info=True)
  try:
    await shutdown_query_graph()
  except Exception:
    _logger.warning("shutdown_query_graph() raised an exception", exc_info=True)
```

- [ ] **Step 9: Remove the dead `ingestion_model` config field**

In `apps/backend/src/second_brain/config.py`, remove line 22:

```python
  ingestion_model: str = "claude-haiku-4-5"
```

so the `# Model names` block reads:

```python
  # Model names
  embedding_model: str = "qwen3-embedding:0.6b"
```

- [ ] **Step 10: Run lint/type-check/full unit suite**

Run: `just lint && just type-check && just test-unit`
Expected: all pass, no errors.

- [ ] **Step 11: Run integration tests (requires Postgres running)**

Run: `just up-all` (if not already running), then `just test-integration`
Expected: all integration tests pass, including the 3 ingestion tests touched in Step 7. If Postgres isn't available in this environment, note that explicitly rather than assuming — this is the one verification step in this task that needs a live dependency.

- [ ] **Step 12: Commit**

```bash
git add apps/backend/src/second_brain/nodes/ingestion_agent.py apps/backend/src/second_brain/config.py apps/backend/src/second_brain/main.py apps/backend/tests/unit/test_nodes/test_ingestion_agent.py apps/backend/tests/integration/test_ingestion_graph.py
git commit -m "refactor: convert ingestion_agent node to BaseAgentNode on ClaudeAgent, drop raw Anthropic client and dead shutdown/config"
```

---

### Task 12: Full-repo verification pass

**Files:** none (verification only).

**Interfaces:** none — this task confirms the whole refactor is coherent end-to-end.

- [ ] **Step 1: Confirm `query_graph.py` needed zero edits**

Run: `git diff main -- apps/backend/src/second_brain/graphs/query_graph.py`
Expected: no output — `query_graph.py` was never touched across Tasks 1–11, per the naming rule in the design spec.

- [ ] **Step 2: Full workspace verification**

Run: `just format lint type-check test-unit`
Expected: all green, no diffs from `format`.

- [ ] **Step 3: Integration verification (if not already confirmed in Task 11)**

Run: `just up-all && just test-integration`
Expected: all integration tests pass.

- [ ] **Step 4: Smoke-test the running system**

Run: `just up-all`, then:

```bash
curl -s -X POST localhost:3001/query -H 'Content-Type: application/json' -d '{"message": "Hello"}'
```

Expected: HTTP 200 with a JSON body containing `final_answer`/`confidence` — confirms `query_graph.py`'s unchanged `add_node` calls actually resolve to the new class instances at runtime (not just at import time in tests).

- [ ] **Step 5: Final commit (if any stray formatting fixes were needed)**

```bash
git status --short
```

If `just format` in Step 2 produced changes not yet committed, stage and commit them:

```bash
git add -u
git commit -m "chore: apply formatting fixes from full-repo verification pass"
```

If nothing changed, skip this step — there is nothing to commit.
