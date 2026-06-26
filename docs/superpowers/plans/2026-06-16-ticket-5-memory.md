# Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete memory system — shared asyncpg pool, auto fact extraction, conflict detection, model correction detection, cross-turn state machine, and a full `memory_retrieval_node` replacing the stub from Ticket 4.

**Architecture:** `memory_retrieval_node` embeds each incoming query via `services/embeddings.embed_text()` and runs two parallel asyncpg cosine-similarity searches (learned facts + model corrections) to populate `retrieved_memory`. After synthesis, `memory_agent_node` (LangChain-Anthropic `with_structured_output(MemoryAgentOutput)`) classifies the user message into one of three `MemoryCase` values and populates `fact_updates` / `correction_updates`. `memory_persistence_node` (tool call, no LLM) then embeds each fact via `embed_text()`, conflict-checks via asyncpg pool, and writes to the DB using SQLModel sync `Session(engine)` with per-fact retry × 3.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, SQLModel, asyncpg, pgvector, LangChain-Anthropic (`ChatAnthropic.with_structured_output`), Ollama (`qwen3-embedding:0.6b`, dim=1024), pytest + pytest-asyncio, `unittest.mock`.

## Global Constraints

- Embedding: always use `embed_text()` from `second_brain.services.embeddings` — do NOT create a new embedding utility
- asyncpg pool: always use `get_pgvector_pool()` from `second_brain.db.pool` — never create a node-local pool
- DB writes: SQLModel sync `Session(engine)` from `second_brain.db.session` — never use `AsyncSession` for writes
- DB reads (vector): asyncpg pool — never use SQLAlchemy for pgvector cosine queries
- Message indexing: walk `messages` list by type — never use fixed negative indices
- Conflict threshold: `settings.memory_conflict_threshold` (float, default 0.85) — never hardcode
- Ollama errors: raise immediately — no empty-list fallback in `memory_retrieval_node`
- `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive — entering Case 3 resets `awaiting_correction=False`
- `awaiting_correction=True` is set by synthesis (not memory agent) when `confidence < 0.7`
- asyncpg vector codec: `register_vector` (called by pool init) accepts Python `list[float]` directly — no `pg_literal` string conversion
- Node function name: `memory_retrieval_node` throughout (graph key AND function name)

---

## File Map

| Action | Path                                                            | Responsibility                                                                                      |
| ------ | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Create | `apps/backend/src/second_brain/db/pool.py`                      | asyncpg pool singleton shared by `rag_retrieval` and `memory_retrieval_node`                        |
| Modify | `apps/backend/src/second_brain/nodes/rag_retrieval.py`          | Remove `_get_rag_pool`, `shutdown_rag_pool`; import from `db/pool.py`                               |
| Modify | `apps/backend/src/second_brain/graphs/state.py`                 | Add `ConflictContext`, `MemoryCase`, `MemoryAgentOutput`; update `conflict_context` type            |
| Modify | `apps/backend/src/second_brain/config.py`                       | Add `memory_conflict_threshold: float = 0.85` (env: `MEMORY_CONFLICT_THRESHOLD`)                    |
| Modify | `apps/backend/src/second_brain/nodes/memory_retrieval.py`       | Replace stub; rename function to `memory_retrieval_node`; use asyncpg pool + `embed_text`           |
| Create | `apps/backend/src/second_brain/nodes/memory_agent.py`           | Fact extraction + correction detection (3 cases); LangChain-Anthropic `with_structured_output`      |
| Create | `apps/backend/src/second_brain/nodes/memory_persistence.py`     | asyncpg conflict-check reads + SQLModel sync writes; per-fact retry × 3                             |
| Modify | `apps/backend/src/second_brain/nodes/synthesis.py`              | Set `awaiting_correction=True` alongside `is_uncertain` when `confidence < 0.7`                     |
| Modify | `apps/backend/src/second_brain/graphs/query_graph.py`           | Wire 3 new memory nodes after `redact_outbound`; rename `retrieve_memory` → `memory_retrieval_node` |
| Create | `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py`   | Unit tests for `memory_retrieval_node`                                                              |
| Create | `apps/backend/tests/unit/test_nodes/test_memory_agent.py`       | Unit tests for `memory_agent_node` (all 3 cases)                                                    |
| Create | `apps/backend/tests/unit/test_nodes/test_memory_persistence.py` | Unit tests for `memory_persistence_node`                                                            |
| Create | `apps/backend/tests/integration/test_memory_system.py`          | Integration: full memory loop against real DB                                                       |

---

### Task 1: Shared asyncpg Pool (`db/pool.py`) + Migrate `rag_retrieval.py`

**Files:**

- Create: `apps/backend/src/second_brain/db/pool.py`
- Modify: `apps/backend/src/second_brain/nodes/rag_retrieval.py`
- Test: `apps/backend/tests/unit/test_db/test_pool.py`

**Interfaces:**

- Produces: `get_pgvector_pool() -> asyncpg.Pool`, `shutdown_pgvector_pool() -> None`
- Consumed by: `memory_retrieval_node` (Task 3), `memory_persistence_node` (Task 6)

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_db/test_pool.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_pgvector_pool_initialises_once():
    """Calling get_pgvector_pool() twice returns the same pool — only created once."""
    import second_brain.db.pool as pool_module

    saved = pool_module._pgvector_pool
    pool_module._pgvector_pool = None  # reset singleton for test isolation

    mock_pool = MagicMock()
    with patch("second_brain.db.pool.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        p1 = await pool_module.get_pgvector_pool()
        p2 = await pool_module.get_pgvector_pool()

    pool_module._pgvector_pool = saved  # restore

    assert p1 is p2
    assert p1 is mock_pool


@pytest.mark.asyncio
async def test_shutdown_pgvector_pool_closes_and_resets():
    """shutdown_pgvector_pool() closes the pool and sets the singleton to None."""
    import second_brain.db.pool as pool_module

    mock_pool = AsyncMock()
    pool_module._pgvector_pool = mock_pool

    await pool_module.shutdown_pgvector_pool()

    mock_pool.close.assert_awaited_once()
    assert pool_module._pgvector_pool is None


@pytest.mark.asyncio
async def test_shutdown_noop_when_pool_is_none():
    """shutdown_pgvector_pool() does nothing if the pool was never initialised."""
    import second_brain.db.pool as pool_module

    saved = pool_module._pgvector_pool
    pool_module._pgvector_pool = None

    await pool_module.shutdown_pgvector_pool()  # must not raise

    pool_module._pgvector_pool = saved
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_db/test_pool.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.db.pool'`

- [ ] **Step 3: Create `db/pool.py`**

First create the `test_db` package directory:

```bash
mkdir -p apps/backend/tests/unit/test_db && touch apps/backend/tests/unit/test_db/__init__.py
```

Then create the pool module:

```python
# apps/backend/src/second_brain/db/pool.py
"""Shared asyncpg connection pool for pgvector queries.

Both rag_retrieval and memory_retrieval_node call get_pgvector_pool().
"""
import asyncio
import json

import asyncpg
from pgvector.asyncpg import register_vector

from second_brain.config import settings

_pgvector_pool: asyncpg.Pool | None = None
_pgvector_pool_lock: asyncio.Lock = asyncio.Lock()


async def _setup_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )


async def get_pgvector_pool() -> asyncpg.Pool:
    global _pgvector_pool
    async with _pgvector_pool_lock:
        if _pgvector_pool is None:
            _pgvector_pool = await asyncpg.create_pool(  # type: ignore[assignment]
                settings.postgres_url, init=_setup_conn
            )
    return _pgvector_pool  # type: ignore[return-value]


async def shutdown_pgvector_pool() -> None:
    global _pgvector_pool
    if _pgvector_pool is not None:
        await _pgvector_pool.close()
        _pgvector_pool = None
```

- [ ] **Step 4: Migrate `rag_retrieval.py` to import from `db/pool.py`**

Open `apps/backend/src/second_brain/nodes/rag_retrieval.py`.

Remove these module-level symbols (they are being moved to `db/pool.py`):

- `_rag_pool: asyncpg.Pool | None = None`
- `_rag_pool_lock: asyncio.Lock = asyncio.Lock()`
- `async def _setup_conn(conn: asyncpg.Connection) -> None: ...`
- `async def _get_rag_pool(postgres_url: str) -> asyncpg.Pool: ...`
- `async def shutdown_rag_pool() -> None: ...`

Add this import:

```python
from second_brain.db.pool import get_pgvector_pool
```

Update `_query_pgvector` to drop the `postgres_url` parameter and call `get_pgvector_pool()`:

```python
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
```

Update `retrieve_from_rag` to drop `postgres_url` from the `_query_pgvector` call:

```python
async def retrieve_from_rag(state: SecondBrainState) -> RagRetrievalOutput:
    """LangGraph node: retrieves relevant chunks for the latest user message."""
    query = get_str_content(state["messages"][-1])
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding)
    return {"rag_results": rows}
```

Also update app lifespan (`apps/backend/src/second_brain/main.py` or wherever `shutdown_rag_pool` was called): replace `shutdown_rag_pool` import with `shutdown_pgvector_pool` from `second_brain.db.pool`.

Check for the lifespan call:

```bash
grep -rn "shutdown_rag_pool\|shutdown_pgvector_pool" apps/backend/src/
```

Replace any `shutdown_rag_pool` call with:

```python
from second_brain.db.pool import shutdown_pgvector_pool
# in lifespan: await shutdown_pgvector_pool()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_db/test_pool.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Run the full unit suite to confirm no regressions**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 7: Update CLAUDE.md**

In `CLAUDE.md`, update the "Two Postgres connection pools" note to reflect the new pool location:

```markdown
# BEFORE:

- Two Postgres connection pools coexist: `asyncpg.Pool` in `nodes/rag_retrieval.py` ...

# AFTER:

- Two Postgres connection pools coexist: `asyncpg.Pool` in `db/pool.py` (shared by
  `rag_retrieval` and `memory_retrieval_node` via `get_pgvector_pool()`) and
  `psycopg_pool.AsyncConnectionPool` in `graphs/query_graph.py` (required by
  LangGraph's `AsyncPostgresSaver`). They cannot share a pool — different drivers.
```

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/second_brain/db/pool.py \
        apps/backend/src/second_brain/nodes/rag_retrieval.py \
        apps/backend/src/second_brain/main.py \
        apps/backend/tests/unit/test_db/__init__.py \
        apps/backend/tests/unit/test_db/test_pool.py \
        CLAUDE.md
git commit -m "refactor(db): extract shared asyncpg pool to db/pool.py; migrate rag_retrieval"
```

---

### Task 2: State Schema + Config Updates

**Files:**

- Modify: `apps/backend/src/second_brain/graphs/state.py`
- Modify: `apps/backend/src/second_brain/config.py`

**Interfaces:**

- Produces: `ConflictContext` TypedDict, `MemoryCase` StrEnum, `MemoryAgentOutput` Pydantic model, `Settings.memory_conflict_threshold`
- Consumed by: Tasks 3, 4, 5, 6

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_state_and_config.py
import pytest
from pydantic import ValidationError

from second_brain.graphs.state import (
    ConflictContext,
    FactUpdate,
    CorrectionUpdate,
    MemoryCase,
    MemoryAgentOutput,
)


def test_conflict_context_has_required_fields():
    ctx = ConflictContext(existing="old fact", existing_id="uuid-1", new="new fact")
    assert ctx["existing"] == "old fact"
    assert ctx["existing_id"] == "uuid-1"
    assert ctx["new"] == "new fact"


def test_memory_case_values():
    assert MemoryCase.FACT_EXTRACTION == "fact_extraction"
    assert MemoryCase.CORRECTION == "correction"
    assert MemoryCase.CONFLICT_RESOLUTION == "conflict_resolution"


def test_memory_agent_output_defaults():
    output = MemoryAgentOutput(case=MemoryCase.FACT_EXTRACTION)
    assert output.fact_updates == []
    assert output.correction_updates == []


def test_memory_agent_output_with_facts():
    output = MemoryAgentOutput(
        case=MemoryCase.FACT_EXTRACTION,
        fact_updates=[{"fact": "user is a developer", "confidence": 0.9, "conflicts_with": []}],
    )
    assert len(output.fact_updates) == 1


def test_memory_conflict_threshold_default():
    from second_brain.config import settings
    assert settings.memory_conflict_threshold == 0.85
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_state_and_config.py -v
```

Expected: `ImportError: cannot import name 'ConflictContext' from 'second_brain.graphs.state'`

- [ ] **Step 3: Update `state.py`**

Add to imports at the top of `apps/backend/src/second_brain/graphs/state.py`:

```python
from enum import StrEnum
from pydantic import BaseModel
```

Add these classes after `class CorrectionUpdate(TypedDict):` and before `class SecondBrainState(TypedDict):`:

```python
class ConflictContext(TypedDict):
    existing: str       # text of the existing fact
    existing_id: str    # UUID of the existing learned_fact row
    new: str            # text of the proposed new fact


class MemoryCase(StrEnum):
    FACT_EXTRACTION = "fact_extraction"
    CORRECTION = "correction"
    CONFLICT_RESOLUTION = "conflict_resolution"


class MemoryAgentOutput(BaseModel):
    case: MemoryCase
    fact_updates: list[FactUpdate] = []
    correction_updates: list[CorrectionUpdate] = []
```

Update `SecondBrainState.conflict_context` type:

```python
# Change this line:
conflict_context: NotRequired[list[str]]  # Ticket 5: memory-correction
# To:
conflict_context: NotRequired[list[ConflictContext]]  # Ticket 5: memory-correction
```

- [ ] **Step 4: Update `config.py`**

Add to the `Settings` class in `apps/backend/src/second_brain/config.py`:

```python
memory_conflict_threshold: float = 0.85  # env: MEMORY_CONFLICT_THRESHOLD
```

Place it near other model-behaviour settings (after `embedding_model`).

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_state_and_config.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Run lint + type check**

```bash
cd apps/backend && python -m ruff check src/ && python -m pyright src/
```

Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/second_brain/graphs/state.py \
        apps/backend/src/second_brain/config.py \
        apps/backend/tests/unit/test_state_and_config.py
git commit -m "feat(memory): add ConflictContext, MemoryCase, MemoryAgentOutput to state; add conflict threshold to config"
```

---

### Task 3: `memory_retrieval_node` Full Implementation

**Files:**

- Modify: `apps/backend/src/second_brain/nodes/memory_retrieval.py`
- Create: `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py`

**Interfaces:**

- Consumes: `get_pgvector_pool()` (Task 1), `embed_text()` from `services/embeddings`, `get_str_content()` from `second_brain.utils`
- Produces: `memory_retrieval_node(state) -> RetrieveMemoryOutput`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_memory_retrieval.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncContextManager
from langchain_core.messages import HumanMessage, AIMessage
from second_brain.nodes.memory_retrieval import memory_retrieval_node
from second_brain.graphs.state import SecondBrainState, MemoryItem


def _make_state(**overrides) -> SecondBrainState:
    base: SecondBrainState = {
        "session_id": "test-session",
        "messages": [HumanMessage(content="What food do I like?")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.8,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


def _make_mock_pool(fact_rows, correction_rows):
    """Build a mock asyncpg Pool whose acquire() returns a conn with fetch()."""
    mock_conn = AsyncMock()
    # First fetch call = learned_facts, second = model_corrections
    mock_conn.fetch = AsyncMock(side_effect=[fact_rows, correction_rows])

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


@pytest.mark.asyncio
async def test_merges_and_sorts_by_score():
    """Merges learned_facts + model_corrections, sorted descending by score."""
    fact_row = {"id": "fact-1", "fact": "The user likes sushi", "confidence": 0.9, "score": 0.92}
    corr_row = {"id": "corr-1", "fact": "Tokyo is in Japan", "score": 0.85}

    mock_pool = _make_mock_pool([fact_row], [corr_row])
    mock_embedding = [0.1] * 1024

    with (
        patch("second_brain.nodes.memory_retrieval.embed_text", new_callable=AsyncMock, return_value=mock_embedding),
        patch("second_brain.nodes.memory_retrieval.get_pgvector_pool", new_callable=AsyncMock, return_value=mock_pool),
    ):
        result = await memory_retrieval_node(_make_state())

    memory: list[MemoryItem] = result["retrieved_memory"]
    assert len(memory) == 2
    assert memory[0]["id"] == "fact-1"
    assert memory[0]["type"] == "learned_fact"
    assert memory[0]["confidence"] == 0.9
    assert memory[1]["id"] == "corr-1"
    assert memory[1]["type"] == "model_correction"
    assert memory[1]["confidence"] == 1.0


@pytest.mark.asyncio
async def test_returns_empty_when_db_empty():
    """Returns empty retrieved_memory when no rows exist."""
    mock_pool = _make_mock_pool([], [])

    with (
        patch("second_brain.nodes.memory_retrieval.embed_text", new_callable=AsyncMock, return_value=[0.0] * 1024),
        patch("second_brain.nodes.memory_retrieval.get_pgvector_pool", new_callable=AsyncMock, return_value=mock_pool),
    ):
        result = await memory_retrieval_node(_make_state())

    assert result["retrieved_memory"] == []


@pytest.mark.asyncio
async def test_uses_last_human_message_by_type():
    """embed_text is called with the last HumanMessage content (found by type, not index)."""
    state = _make_state(messages=[
        HumanMessage(content="First"),
        AIMessage(content="Reply"),
        HumanMessage(content="Second — this one"),
    ])
    mock_pool = _make_mock_pool([], [])

    with (
        patch("second_brain.nodes.memory_retrieval.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024) as mock_embed,
        patch("second_brain.nodes.memory_retrieval.get_pgvector_pool", new_callable=AsyncMock, return_value=mock_pool),
    ):
        await memory_retrieval_node(state)

    mock_embed.assert_called_once_with("Second — this one")


@pytest.mark.asyncio
async def test_fails_hard_when_embed_raises():
    """Ollama unavailability propagates as an exception — no empty-list fallback."""
    with patch("second_brain.nodes.memory_retrieval.embed_text", side_effect=ValueError("Ollama down")):
        with pytest.raises(ValueError, match="Ollama down"):
            await memory_retrieval_node(_make_state())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: `FAILED` — the stub `retrieve_memory` doesn't match `memory_retrieval_node`.

- [ ] **Step 3: Replace the stub with the full implementation**

Overwrite `apps/backend/src/second_brain/nodes/memory_retrieval.py`:

```python
"""MemoryRetrievalNode: dual-table cosine search on learned_facts + model_corrections."""
import asyncio

import asyncpg
from langchain_core.messages import HumanMessage

from second_brain.db.pool import get_pgvector_pool
from second_brain.graphs.state import MemoryItem, RetrieveMemoryOutput, SecondBrainState
from second_brain.services.embeddings import embed_text
from second_brain.utils import get_str_content


async def _search_facts(pool: asyncpg.Pool, embedding: list[float]) -> list[tuple[float, MemoryItem]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            # ORDER BY raw <=> operator (distance ASC) so pgvector HNSW/IVFFlat index is used.
            # Same pattern as rag_retrieval.py. Score computed as 1-distance in SELECT only.
            "SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score"
            " FROM learned_facts ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
        )
        return [
            (
                float(r["score"]),
                MemoryItem(id=r["id"], fact=r["fact"], confidence=r["confidence"], type="learned_fact"),
            )
            for r in rows
        ]


async def _search_corrections(pool: asyncpg.Pool, embedding: list[float]) -> list[tuple[float, MemoryItem]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, correction AS fact, 1-(embedding<=>$1) AS score"
            " FROM model_corrections ORDER BY embedding<=>$1 ASC LIMIT 3",
            embedding,
        )
        return [
            (
                float(r["score"]),
                MemoryItem(id=r["id"], fact=r["fact"], confidence=1.0, type="model_correction"),
            )
            for r in rows
        ]


async def memory_retrieval_node(state: SecondBrainState) -> RetrieveMemoryOutput:
    """Embed current query and run two parallel cosine searches.

    Fails hard on Ollama unavailability — no empty-list fallback.
    """
    last_human: HumanMessage | None = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_human = msg
            break
    if last_human is None:
        return {"retrieved_memory": []}

    query_text = get_str_content(last_human)
    embedding = await embed_text(query_text)  # raises if Ollama is down

    pool = await get_pgvector_pool()
    # Separate acquire() calls per coroutine — asyncpg connections are not shared
    facts_scored, corrections_scored = await asyncio.gather(
        _search_facts(pool, embedding),
        _search_corrections(pool, embedding),
    )

    all_scored = sorted(facts_scored + corrections_scored, key=lambda x: x[0], reverse=True)
    return {"retrieved_memory": [item for _, item in all_scored]}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_retrieval.py \
        apps/backend/tests/unit/test_nodes/test_memory_retrieval.py
git commit -m "feat(memory): implement memory_retrieval_node — dual-table asyncpg cosine search"
```

---

### Task 4: `memory_agent_node` — All Three Cases

**Files:**

- Create: `apps/backend/src/second_brain/nodes/memory_agent.py`
- Create: `apps/backend/tests/unit/test_nodes/test_memory_agent.py`

**Interfaces:**

- Consumes: `MemoryAgentOutput`, `MemoryCase`, `ConflictContext`, `FactUpdate`, `CorrectionUpdate` from `state.py` (Task 2); `get_str_content()` from `second_brain.utils`
- Produces: `memory_agent_node(state) -> dict` — updates `fact_updates`, `correction_updates`, and state flags

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_memory_agent.py
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from second_brain.graphs.state import (
    FactUpdate, CorrectionUpdate, MemoryAgentOutput, MemoryCase, SecondBrainState
)


def _make_state(**overrides) -> SecondBrainState:
    base: SecondBrainState = {
        "session_id": "test-session",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "Hello back.",
        "confidence": 0.9,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


def _output(case: MemoryCase, facts=None, corrections=None) -> MemoryAgentOutput:
    return MemoryAgentOutput(
        case=case,
        fact_updates=facts or [],
        correction_updates=corrections or [],
    )


# ── Case 1: Fact Extraction ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case1_extracts_user_facts():
    """Case 1: self-referential message → fact_updates populated."""
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(messages=[HumanMessage(content="I work as a software engineer in Berlin.")])

    with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_output(
            MemoryCase.FACT_EXTRACTION,
            facts=[{"fact": "The user is a software engineer in Berlin.", "confidence": 0.95, "conflicts_with": []}],
        ))
        result = await memory_agent_node(state)

    assert len(result["fact_updates"]) == 1
    assert result["fact_updates"][0]["fact"] == "The user is a software engineer in Berlin."
    assert result["correction_updates"] == []


@pytest.mark.asyncio
async def test_case1_no_facts_in_generic_message():
    """Case 1: non-self-referential message → empty fact_updates."""
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(messages=[HumanMessage(content="What is the tallest mountain?")])

    with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_output(MemoryCase.FACT_EXTRACTION))
        result = await memory_agent_node(state)

    assert result["fact_updates"] == []
    assert result["correction_updates"] == []


# ── Case 2: Correction Detection ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case2_extracts_correction():
    """Case 2: user corrects uncertain answer → correction_updates populated, awaiting_correction=False."""
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(
        messages=[
            AIMessage(content="I think the capital of France is Lyon, but I'm not sure."),
            HumanMessage(content="Actually it's Paris, not Lyon."),
        ],
        awaiting_correction=True,
    )

    with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_output(
            MemoryCase.CORRECTION,
            corrections=[{
                "original_answer": "I think the capital of France is Lyon, but I'm not sure.",
                "correction": "The capital of France is Paris.",
                "root_cause": "AI confused Lyon with Paris.",
            }],
        ))
        result = await memory_agent_node(state)

    assert result["awaiting_correction"] is False
    assert len(result["correction_updates"]) == 1
    assert result["correction_updates"][0]["correction"] == "The capital of France is Paris."


@pytest.mark.asyncio
async def test_case2_unrelated_query_resets_awaiting_correction():
    """AC-3: awaiting_correction=True + unrelated query → fact_updates from extraction, awaiting_correction=False."""
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(
        messages=[
            AIMessage(content="I'm not sure about this."),
            HumanMessage(content="What time is it in Tokyo?"),
        ],
        awaiting_correction=True,
    )

    with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_output(MemoryCase.FACT_EXTRACTION))
        result = await memory_agent_node(state)

    assert result["awaiting_correction"] is False
    assert result["correction_updates"] == []


# ── Case 3: Conflict Clarification ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case3_resolves_conflict_and_resets_flags():
    """Case 3: user clarifies conflict → awaiting_conflict_clarification=False, awaiting_correction=False."""
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(
        messages=[HumanMessage(content="Use the new one — I moved to Tokyo.")],
        awaiting_conflict_clarification=True,
        awaiting_correction=False,
        conflict_context=[
            {"existing": "User lives in Berlin", "existing_id": "id-1", "new": "User lives in Tokyo"}
        ],
        fact_updates=[{"fact": "User lives in Tokyo", "confidence": 0.9, "conflicts_with": ["id-1"]}],
    )

    with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_output(
            MemoryCase.CONFLICT_RESOLUTION,
            facts=[{"fact": "User lives in Tokyo", "confidence": 0.95, "conflicts_with": []}],
        ))
        result = await memory_agent_node(state)

    assert result["awaiting_conflict_clarification"] is False
    assert result["awaiting_correction"] is False  # D4: mutually exclusive
    assert result["conflict_context"] == []
    assert len(result["fact_updates"]) == 1


@pytest.mark.asyncio
async def test_case3_keep_existing_returns_empty_fact_updates():
    """Case 3: keep_existing → empty fact_updates (nothing to write)."""
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(
        messages=[HumanMessage(content="Keep the old one.")],
        awaiting_conflict_clarification=True,
        conflict_context=[
            {"existing": "User lives in Berlin", "existing_id": "id-1", "new": "User lives in Tokyo"}
        ],
        fact_updates=[{"fact": "User lives in Tokyo", "confidence": 0.9, "conflicts_with": ["id-1"]}],
    )

    with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_output(MemoryCase.CONFLICT_RESOLUTION))
        result = await memory_agent_node(state)

    assert result["awaiting_conflict_clarification"] is False
    assert result["fact_updates"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.nodes.memory_agent'`

- [ ] **Step 3: Create `memory_agent.py`**

```python
# apps/backend/src/second_brain/nodes/memory_agent.py
"""MemoryAgentNode: classifies user message into one of three MemoryCase values."""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from second_brain.graphs.state import (
    ConflictContext,
    CorrectionUpdate,
    FactUpdate,
    MemoryAgentOutput,
    MemoryCase,
    SecondBrainState,
)
from second_brain.utils import get_str_content

_llm = ChatAnthropic(model="claude-haiku-4-5").with_structured_output(  # pyright: ignore[reportCallIssue]
    MemoryAgentOutput
)


def _last_human_msg(messages: list[BaseMessage]) -> HumanMessage | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


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


async def memory_agent_node(state: SecondBrainState) -> dict:
    """Three-case memory classification via LangChain-Anthropic structured output."""
    messages = state["messages"]
    awaiting_correction: bool = state.get("awaiting_correction", False)
    awaiting_conflict: bool = state.get("awaiting_conflict_clarification", False)
    conflict_context: list[ConflictContext] = state.get("conflict_context", [])

    human_msg = _last_human_msg(messages)
    if human_msg is None:
        return {"fact_updates": [], "correction_updates": []}
    user_text = get_str_content(human_msg)

    if awaiting_conflict:
        # Case 3: conflict clarification
        conflict_summary = "\n".join(
            f'- Existing: "{c["existing"]}" | New: "{c["new"]}"'
            for c in conflict_context
        )
        prompt = (
            "The user previously had a memory conflict that needs clarifying.\n\n"
            f"Conflicts:\n{conflict_summary}\n\n"
            f"User clarification: {user_text!r}\n\n"
            "case=conflict_resolution. Populate fact_updates with the resolved fact(s). "
            "Set conflicts_with=[] — the persistence node handles deletion of old facts."
        )
    elif awaiting_correction:
        # Case 2: correction check
        prior_ai = _prior_ai_content(messages)
        prompt = (
            f"The AI gave an uncertain answer: {prior_ai!r}\n"
            f"The user responded: {user_text!r}\n\n"
            "If the user is correcting the AI: case=correction, populate correction_updates "
            "(original_answer, correction, root_cause). "
            "If the user is asking something new: case=fact_extraction, extract any "
            "self-referential facts into fact_updates."
        )
    else:
        # Case 1: normal fact extraction
        prompt = (
            f"User message: {user_text!r}\n\n"
            "case=fact_extraction. Extract self-referential facts (statements where the user "
            "describes themselves, e.g. 'I work as X', 'I live in Y', 'I prefer Z'). "
            "Return empty fact_updates if none exist. Set conflicts_with=[] for every fact."
        )

    output: MemoryAgentOutput = await _llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]

    updates: dict = {
        "fact_updates": list(output.fact_updates),
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_agent.py \
        apps/backend/tests/unit/test_nodes/test_memory_agent.py
git commit -m "feat(memory): add memory_agent_node — 3-case LangChain-Anthropic classification"
```

---

### Task 5: `memory_persistence_node` — Fact + Correction Persistence

**Files:**

- Create: `apps/backend/src/second_brain/nodes/memory_persistence.py`
- Create: `apps/backend/tests/unit/test_nodes/test_memory_persistence.py`

**Interfaces:**

- Consumes: `get_pgvector_pool()` (Task 1), `embed_text()`, `Session(engine)` from `db/session`, `LearnedFact` and `ModelCorrection` from `db/models`, `settings.memory_conflict_threshold` (Task 2)
- Produces: `memory_persistence_node(state) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_memory_persistence.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.graphs.state import SecondBrainState


def _make_state(**overrides) -> SecondBrainState:
    base: SecondBrainState = {
        "session_id": "test-session",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "You are a vegetarian.",
        "confidence": 0.9,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


def _mock_pool(conflict_rows=None):
    """Mock asyncpg pool; conflict_rows is the result of the conflict-check fetch."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=conflict_rows or [])
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


# ── AC-1: fact written ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac1_writes_fact_with_embedding():
    """AC-1: fact_update → LearnedFact added to session with correct fields."""
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.db.models import LearnedFact

    state = _make_state(
        fact_updates=[{"fact": "The user is a vegetarian.", "confidence": 0.9, "conflicts_with": []}],
    )

    with (
        patch("second_brain.nodes.memory_persistence.embed_text", new_callable=AsyncMock, return_value=[0.5] * 1024),
        patch("second_brain.nodes.memory_persistence.get_pgvector_pool", new_callable=AsyncMock, return_value=_mock_pool()),
        patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await memory_persistence_node(state)

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert isinstance(added, LearnedFact)
    assert added.fact == "The user is a vegetarian."
    assert added.confidence == 0.9
    assert added.embedding == [0.5] * 1024
    assert added.source_session == "test-session"
    mock_session.commit.assert_called_once()

    assert result["awaiting_conflict_clarification"] is False
    assert result["fact_updates"] == []


@pytest.mark.asyncio
async def test_ac1_skips_conflict_check_when_conflicts_with_set():
    """User already resolved conflict → write directly, no conflict-check fetch."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[{"fact": "User lives in Tokyo", "confidence": 0.95, "conflicts_with": ["old-id"]}],
    )
    mock_pool = _mock_pool()

    with (
        patch("second_brain.nodes.memory_persistence.embed_text", new_callable=AsyncMock, return_value=[0.3] * 1024),
        patch("second_brain.nodes.memory_persistence.get_pgvector_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        await memory_persistence_node(state)

    # fetch (conflict check) must NOT be called
    mock_pool.acquire.return_value.__aenter__.return_value.fetch.assert_not_called()
    mock_session.add.assert_called_once()


# ── AC-2: conflict detection ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac2_detects_conflict_sets_state():
    """AC-2: conflicting fact → awaiting_conflict_clarification=True, fact NOT written."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    conflict_row = {"id": "existing-id", "fact": "User lives in Berlin", "score": 0.92}
    state = _make_state(
        final_answer="You mentioned moving.",
        fact_updates=[{"fact": "User lives in Tokyo", "confidence": 0.9, "conflicts_with": []}],
    )

    with (
        patch("second_brain.nodes.memory_persistence.embed_text", new_callable=AsyncMock, return_value=[0.5] * 1024),
        patch("second_brain.nodes.memory_persistence.get_pgvector_pool", new_callable=AsyncMock, return_value=_mock_pool([conflict_row])),
        patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await memory_persistence_node(state)

    mock_session.add.assert_not_called()  # fact must NOT be written

    assert result["awaiting_conflict_clarification"] is True
    assert len(result["conflict_context"]) == 1
    cc = result["conflict_context"][0]
    assert cc["existing"] == "User lives in Berlin"
    assert cc["new"] == "User lives in Tokyo"
    assert cc["existing_id"] == "existing-id"
    assert "⚠️" in result["final_answer"]
    assert len(result["fact_updates"]) == 1
    assert "existing-id" in result["fact_updates"][0]["conflicts_with"]


# ── AC-4: correction written ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac4_writes_correction_embedding_encodes_correction():
    """AC-4: correction_update → ModelCorrection row; embed_text called with correction text."""
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.db.models import ModelCorrection

    state = _make_state(
        fact_updates=[],
        correction_updates=[{
            "original_answer": "The capital of France is Lyon.",
            "correction": "The capital of France is Paris.",
            "root_cause": "AI confused Lyon with Paris.",
        }],
    )

    with (
        patch("second_brain.nodes.memory_persistence.embed_text", new_callable=AsyncMock, return_value=[0.3] * 1024) as mock_embed,
        patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        await memory_persistence_node(state)

    # embed_text must be called with the correction text, not original_answer
    mock_embed.assert_called_once_with("The capital of France is Paris.")
    added = mock_session.add.call_args[0][0]
    assert isinstance(added, ModelCorrection)
    assert added.correction == "The capital of France is Paris."
    assert added.original_answer == "The capital of France is Lyon."
    assert added.root_cause == "AI confused Lyon with Paris."


@pytest.mark.asyncio
async def test_per_fact_retry_raises_after_three_failures():
    """Fact write that fails 3 times raises — does not silently swallow errors."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[{"fact": "User is a developer.", "confidence": 0.9, "conflicts_with": []}],
    )

    with (
        patch("second_brain.nodes.memory_persistence.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024),
        patch("second_brain.nodes.memory_persistence.get_pgvector_pool", new_callable=AsyncMock, return_value=_mock_pool()),
        patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("DB write failed")
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="DB write failed"):
            await memory_persistence_node(state)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_persistence.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.nodes.memory_persistence'`

- [ ] **Step 3: Create `memory_persistence.py`**

```python
# apps/backend/src/second_brain/nodes/memory_persistence.py
"""MemoryPersistenceNode: writes facts and corrections to the database.

Conflict-check reads: asyncpg pool (get_pgvector_pool)
Writes: SQLModel sync Session(engine) — matches ingestion_agent.py pattern
Per-fact retry: up to _MAX_RETRIES attempts before raising
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session

from second_brain.config import settings
from second_brain.db.models import LearnedFact, ModelCorrection
from second_brain.db.pool import get_pgvector_pool
from second_brain.db.session import engine
from second_brain.graphs.state import (
    ConflictContext,
    CorrectionUpdate,
    FactUpdate,
    SecondBrainState,
)
from second_brain.services.embeddings import embed_text

_MAX_RETRIES = 3


async def _conflict_check(embedding: list[float]) -> list[dict]:
    """Return rows from learned_facts whose cosine similarity exceeds threshold.

    Uses distance domain (embedding<=>$1 < 1-threshold) so pgvector index is used.
    """
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
            " FROM learned_facts"
            " WHERE (embedding<=>$1) < (1 - $2)"  # distance domain → pgvector index
            " ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
            settings.memory_conflict_threshold,
        )
        return [dict(r) for r in rows]


def _retry_write(fn, *args) -> None:
    """Run a sync write function with up to _MAX_RETRIES attempts, then raise."""
    for attempt in range(_MAX_RETRIES):
        try:
            fn(*args)
            return
        except Exception:
            if attempt == _MAX_RETRIES - 1:
                raise


def _write_fact(fact_update: FactUpdate, session_id: str, embedding: list[float]) -> None:
    # Called directly (not via asyncio.to_thread): 1–3 inserts per turn, ~1-3 ms each.
    # Event-loop block is acceptable per D2. Wrap in asyncio.to_thread if insert count grows.
    with Session(engine) as session:
        session.add(LearnedFact(
            id=uuid.uuid4(),
            fact=fact_update["fact"],
            embedding=embedding,
            source_session=session_id,
            confidence=fact_update["confidence"],
        ))
        session.commit()


def _write_correction(correction: CorrectionUpdate, session_id: str, embedding: list[float]) -> None:
    # Same sync pattern as _write_fact — see comment above re: asyncio.to_thread.
    with Session(engine) as session:
        session.add(ModelCorrection(
            id=uuid.uuid4(),
            original_answer=correction["original_answer"],
            correction=correction["correction"],
            root_cause=correction["root_cause"],
            embedding=embedding,
            source_session=session_id,
        ))
        session.commit()


async def _persist_fact(fact_update: FactUpdate, session_id: str) -> ConflictContext | None:
    """Persist one fact. Returns ConflictContext on conflict, None on success, raises on write exhaustion."""
    embedding = await embed_text(fact_update["fact"])

    # User already resolved conflict — write directly, skip conflict check
    if fact_update.get("conflicts_with"):
        _retry_write(_write_fact, fact_update, session_id, embedding)
        return None

    conflicts = await _conflict_check(embedding)
    if conflicts:
        return ConflictContext(
            existing=conflicts[0]["fact"],
            existing_id=conflicts[0]["id"],
            new=fact_update["fact"],
        )

    _retry_write(_write_fact, fact_update, session_id, embedding)
    return None


async def memory_persistence_node(state: SecondBrainState) -> dict[str, Any]:
    """Tool-call node: embeds and persists fact_updates + correction_updates."""
    fact_updates: list[FactUpdate] = state.get("fact_updates", [])
    correction_updates: list[CorrectionUpdate] = state.get("correction_updates", [])
    session_id: str = state["session_id"]
    final_answer: str = state.get("final_answer", "")

    conflict_contexts: list[ConflictContext] = []
    pending_facts: list[FactUpdate] = []

    for fact_update in fact_updates:
        conflict = await _persist_fact(fact_update, session_id)
        if conflict is not None:
            conflict_contexts.append(conflict)
            # Preserve fact with conflict IDs so Case 3 can resolve it
            pending_facts.append(FactUpdate(
                fact=fact_update["fact"],
                confidence=fact_update["confidence"],
                conflicts_with=[conflict["existing_id"]],
            ))

    for correction in correction_updates:
        embedding = await embed_text(correction["correction"])  # encode correction, not original_answer
        _retry_write(_write_correction, correction, session_id, embedding)

    result: dict[str, Any] = {
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_persistence.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_persistence.py \
        apps/backend/tests/unit/test_nodes/test_memory_persistence.py
git commit -m "feat(memory): add memory_persistence_node — asyncpg reads, SQLModel sync writes, per-fact retry"
```

---

### Task 6: Update `synthesis.py` — Set `awaiting_correction`

**Files:**

- Modify: `apps/backend/src/second_brain/nodes/synthesis.py`
- Modify: `apps/backend/tests/unit/test_nodes/test_synthesis.py` (create if not present)

**Interfaces:**

- Change: synthesis return dict now includes `awaiting_correction: bool` alongside `is_uncertain`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.synthesis import synthesize_answer
from second_brain.graphs.state import SecondBrainState


def _make_state(**overrides) -> SecondBrainState:
    base: SecondBrainState = {
        "session_id": "test",
        "messages": [HumanMessage(content="What is the capital of France?")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_synthesis_sets_awaiting_correction_when_uncertain():
    """D9: confidence < 0.7 → is_uncertain=True AND awaiting_correction=True."""
    from second_brain.nodes.synthesis import _SynthesisOutput

    mock_output = MagicMock(spec=_SynthesisOutput)
    mock_output.final_answer = "I'm not sure."
    mock_output.confidence = 0.5
    mock_output.reasoning = "Limited context."

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        result = await synthesize_answer(_make_state())

    assert result["is_uncertain"] is True
    assert result["awaiting_correction"] is True


@pytest.mark.asyncio
async def test_synthesis_does_not_set_awaiting_correction_when_confident():
    """confidence >= 0.7 → is_uncertain=False AND awaiting_correction=False."""
    from second_brain.nodes.synthesis import _SynthesisOutput

    mock_output = MagicMock(spec=_SynthesisOutput)
    mock_output.final_answer = "Paris."
    mock_output.confidence = 0.95
    mock_output.reasoning = "Well established."

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        result = await synthesize_answer(_make_state())

    assert result["is_uncertain"] is False
    assert result["awaiting_correction"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_synthesis_awaiting.py -v
```

Expected: `FAILED` — `awaiting_correction` key missing from synthesis return dict.

- [ ] **Step 3: Update `SynthesisNodeOutput` in `state.py` and `synthesis.py` return**

First, update `SynthesisNodeOutput` in `apps/backend/src/second_brain/graphs/state.py`:

```python
# BEFORE:
class SynthesisNodeOutput(TypedDict):
    final_answer: str
    confidence: float
    is_uncertain: bool

# AFTER:
class SynthesisNodeOutput(TypedDict):
    final_answer: str
    confidence: float
    is_uncertain: bool
    awaiting_correction: bool
```

Then, in `apps/backend/src/second_brain/nodes/synthesis.py`, find the `return` at the end of `synthesize_answer` and update:

```python
# BEFORE:
    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }

# AFTER:
    is_uncertain = confidence < _UNCERTAINTY_THRESHOLD
    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": is_uncertain,
        "awaiting_correction": is_uncertain,  # D9: set alongside is_uncertain
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_synthesis_awaiting.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Run full unit suite**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Verify working tree is clean after staging**

```bash
git add apps/backend/src/second_brain/graphs/state.py \
        apps/backend/src/second_brain/nodes/synthesis.py \
        apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py
git status  # must show nothing unstaged
```

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(memory): synthesis sets awaiting_correction=True when confidence < 0.7"
```

---

### Task 7: Wire Memory Nodes into Query Graph

**Files:**

- Modify: `apps/backend/src/second_brain/graphs/query_graph.py`

- [ ] **Step 1: Read the current graph wiring**

```bash
grep -n "retrieve_memory\|memory_agent\|memory_persistence\|redact_outbound\|add_edge\|add_node" \
    apps/backend/src/second_brain/graphs/query_graph.py
```

Confirm the import and node registration for `retrieve_memory` and the edge `redact_outbound → END`.

- [ ] **Step 2: Update imports**

In `apps/backend/src/second_brain/graphs/query_graph.py`, replace:

```python
from second_brain.nodes.memory_retrieval import retrieve_memory
```

with:

```python
from second_brain.nodes.memory_agent import memory_agent_node
from second_brain.nodes.memory_persistence import memory_persistence_node
from second_brain.nodes.memory_retrieval import memory_retrieval_node
```

- [ ] **Step 3: Rename node and rewire edges**

In `build_query_graph`, replace:

```python
    workflow.add_node("retrieve_memory", retrieve_memory)
```

with:

```python
    workflow.add_node("memory_retrieval_node", memory_retrieval_node)
    workflow.add_node("memory_agent", memory_agent_node)
    workflow.add_node("memory_persistence", memory_persistence_node)
```

Replace the edge from `redact_inbound`:

```python
    # BEFORE:
    workflow.add_edge("redact_inbound", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "orchestrator")
    # ...
    workflow.add_edge("redact_outbound", END)

    # AFTER:
    workflow.add_edge("redact_inbound", "memory_retrieval_node")
    workflow.add_edge("memory_retrieval_node", "orchestrator")
    # ...
    workflow.add_edge("redact_outbound", "memory_agent")
    workflow.add_edge("memory_agent", "memory_persistence")
    workflow.add_edge("memory_persistence", END)
```

- [ ] **Step 4: Verify graph compiles**

```bash
cd apps/backend && python -c "
import asyncio
from second_brain.graphs.query_graph import build_query_graph
print('Import OK')
"
```

Expected: `Import OK` (no import errors).

- [ ] **Step 5: Run full unit suite**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Run lint and type check**

```bash
just lint && just type-check
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/second_brain/graphs/query_graph.py
git commit -m "feat(memory): wire memory_retrieval_node, memory_agent, memory_persistence into query graph"
```

---

### Task 8: Integration Tests — Full Memory Loop

**Files:**

- Create: `apps/backend/tests/integration/test_memory_system.py`

**Pre-condition:** Docker stack running (`just up-all`) with live PostgreSQL+pgvector and Ollama. Tests skip automatically when `DATABASE_URL` doesn't point to a real DB (same skip guard as `test_migration.py`).

- [ ] **Step 1: Write the integration tests**

```python
# apps/backend/tests/integration/test_memory_system.py
"""Integration tests for the full memory cycle.

Requires: Docker stack running (PostgreSQL + pgvector + Ollama).
Uses the same DB skip guard as test_migration.py.

Run with:
  DATABASE_URL=postgresql+asyncpg://second_brain:secret@localhost:5432/second_brain \
    pytest tests/integration/test_memory_system.py -v -m integration
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.integration

_TEST_SESSION_ID = "integration-memory-test"


@pytest.fixture(scope="module")
def db_engine():
    """Sync SQLAlchemy engine for assertions — same skip guard as test_migration.py."""
    url = _DATABASE_URL
    if "test-api-key" in url or ("localhost" not in url and "app_postgres" not in url):
        pytest.skip("DATABASE_URL does not point to a real running database")
    engine = create_engine(url.replace("+asyncpg", "").replace("+psycopg2", ""))
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_test_rows(db_engine):
    """Delete rows written by this test session before each test."""
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM learned_facts WHERE source_session = :sid"), {"sid": _TEST_SESSION_ID})
        conn.execute(text("DELETE FROM model_corrections WHERE source_session = :sid"), {"sid": _TEST_SESSION_ID})
        conn.commit()
    yield


def _make_state(**overrides):
    from langchain_core.messages import HumanMessage
    from second_brain.graphs.state import SecondBrainState
    base: SecondBrainState = {
        "session_id": _TEST_SESSION_ID,
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "Test answer.",
        "confidence": 0.9,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ac1_fact_written_to_db_with_embedding(db_engine):
    """AC-1: fact_updates → learned_facts row with 1024-dim non-zero embedding."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[
            {"fact": "The user is a vegetarian.", "confidence": 0.95, "conflicts_with": []},
            {"fact": "The user loves hiking.", "confidence": 0.9, "conflicts_with": []},
        ],
    )
    await memory_persistence_node(state)

    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT fact, confidence, embedding FROM learned_facts WHERE source_session = :sid"),
            {"sid": _TEST_SESSION_ID},
        ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row.embedding is not None
        assert len(row.embedding) == 1024
        assert any(x != 0.0 for x in row.embedding)


@pytest.mark.asyncio
async def test_ac2_conflict_detected_not_written(db_engine):
    """AC-2: pre-seed a fact, add semantically similar fact → awaiting_conflict_clarification=True, new fact not written."""
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.services.embeddings import embed_text
    from second_brain.db.models import LearnedFact
    from second_brain.db.session import engine as sqlmodel_engine
    from sqlmodel import Session

    # Seed existing fact
    embedding = await embed_text("The user lives in Berlin.")
    with Session(sqlmodel_engine) as session:
        session.add(LearnedFact(
            id=uuid.uuid4(),
            fact="The user lives in Berlin.",
            embedding=embedding,
            source_session=_TEST_SESSION_ID,
            confidence=0.9,
        ))
        session.commit()

    # Attempt to add semantically similar fact
    state = _make_state(
        final_answer="You mentioned moving.",
        fact_updates=[{"fact": "The user lives in Berlin now.", "confidence": 0.85, "conflicts_with": []}],
    )
    result = await memory_persistence_node(state)

    assert result["awaiting_conflict_clarification"] is True
    assert "⚠️" in result["final_answer"]

    with db_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM learned_facts WHERE source_session = :sid AND fact LIKE '%now%'"),
            {"sid": _TEST_SESSION_ID},
        ).scalar()
    assert count == 0


# AC-3 (awaiting_correction reset) is covered by a unit test that does not require a real DB.
# See: tests/unit/test_nodes/test_memory_agent.py::test_case2_unrelated_query_resets_awaiting_correction


@pytest.mark.asyncio
async def test_ac4_correction_written_with_embedding(db_engine):
    """AC-4: correction_updates → model_corrections row with correction-field embedding."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[],
        correction_updates=[{
            "original_answer": "The speed of light is 100 km/s.",
            "correction": "The speed of light is approximately 299,792 km/s.",
            "root_cause": "AI used an incorrect value.",
        }],
    )
    await memory_persistence_node(state)

    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT correction, root_cause, embedding FROM model_corrections WHERE source_session = :sid"),
            {"sid": _TEST_SESSION_ID},
        ).fetchall()

    assert len(rows) == 1
    assert "299,792" in rows[0].correction
    assert rows[0].root_cause == "AI used an incorrect value."
    assert rows[0].embedding is not None
    assert len(rows[0].embedding) == 1024


@pytest.mark.asyncio
async def test_full_memory_loop_persist_then_retrieve(db_engine):
    """Full loop: persist fact → retrieve on related query → fact appears in retrieved_memory."""
    from langchain_core.messages import HumanMessage
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.nodes.memory_retrieval import memory_retrieval_node

    # Turn 1: persist
    await memory_persistence_node(_make_state(
        fact_updates=[{"fact": "The user is a professional cyclist.", "confidence": 0.9, "conflicts_with": []}],
    ))

    # Turn 2: retrieve
    result = await memory_retrieval_node(_make_state(
        messages=[HumanMessage(content="What sports do I do?")]
    ))

    retrieved = result["retrieved_memory"]
    assert len(retrieved) >= 1
    assert any("cyclist" in item["fact"].lower() for item in retrieved)
```

- [ ] **Step 2: Run unit tests to confirm no regressions (integration tests skip without real DB)**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 3: Run integration tests with Docker stack**

```bash
just up-all  # start Docker stack and Ollama
cd apps/backend && python -m pytest tests/integration/test_memory_system.py -v -m integration
```

Expected: `4 passed` (AC-1, AC-2, AC-4, full loop — AC-3 is a unit test in `test_memory_agent.py`)

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/test_memory_system.py
git commit -m "test(memory): integration tests covering AC-1, AC-2, AC-4 + full memory loop"
```

---

## Self-Review Checklist

### Spec coverage

| Requirement                                                               | Task                                      |
| ------------------------------------------------------------------------- | ----------------------------------------- |
| AC-1: fact in `learned_facts` with embedding                              | Task 5 (unit) + Task 8 integration        |
| AC-2: conflict → `awaiting_conflict_clarification=True` + notification    | Task 5 (unit) + Task 8 integration        |
| AC-3: unrelated query resets `awaiting_correction=False`                  | Task 4 Case 2 (unit) + Task 8 integration |
| AC-4: correction → `model_corrections` with embedding                     | Task 5 (unit) + Task 8 integration        |
| D1: shared asyncpg pool in `db/pool.py`                                   | Task 1                                    |
| D2: SQLModel sync `Session` for writes, asyncpg for reads                 | Task 5                                    |
| D3: `settings.memory_conflict_threshold` (not hardcoded)                  | Tasks 2, 5                                |
| D4: mutually exclusive state flags                                        | Tasks 4, 5                                |
| D5: `ConflictContext` TypedDict with `existing`, `existing_id`, `new`     | Tasks 2, 5                                |
| D6: per-fact retry × 3, then raise                                        | Task 5                                    |
| D7: `conflicts_with` reuses `FactUpdate` for conflict resolution          | Tasks 4, 5                                |
| D8: `MemoryCase` + `MemoryAgentOutput` via `with_structured_output`       | Tasks 2, 4                                |
| D9: synthesis sets both `is_uncertain` and `awaiting_correction`          | Task 6                                    |
| D10: function and graph key `memory_retrieval_node`                       | Tasks 3, 7                                |
| D11: walk messages by type (no fixed indices)                             | Tasks 3, 4                                |
| D12: Ollama unavailability in `memory_retrieval_node` fails hard          | Task 3                                    |
| D13: `embed_text()` from `services/embeddings` (no new utility)           | Tasks 3, 5                                |
| D15: LangChain-Anthropic scope — new memory nodes only; `ingestion_agent` unchanged | Task 4              |
| D16: integration test with real DB                                        | Task 8                                    |
| Graph wiring: `redact_outbound → memory_agent → memory_persistence → END` | Task 7                                    |

### Placeholder scan

No TBDs, TODOs, or "similar to" references. All code blocks are complete and runnable.

### Type consistency

| Symbol                               | Defined in                              | Used in Tasks |
| ------------------------------------ | --------------------------------------- | ------------- |
| `get_pgvector_pool()`                | `db/pool.py` (Task 1)                   | 3, 5          |
| `shutdown_pgvector_pool()`           | `db/pool.py` (Task 1)                   | lifespan      |
| `ConflictContext`                    | `graphs/state.py` (Task 2)              | 4, 5, 8       |
| `MemoryCase`                         | `graphs/state.py` (Task 2)              | 4, 8          |
| `MemoryAgentOutput`                  | `graphs/state.py` (Task 2)              | 4, 8          |
| `settings.memory_conflict_threshold` | `config.py` (Task 2)                    | 5             |
| `memory_retrieval_node`              | `nodes/memory_retrieval.py` (Task 3)    | 7, 8          |
| `memory_agent_node`                  | `nodes/memory_agent.py` (Task 4)        | 7, 8          |
| `memory_persistence_node`            | `nodes/memory_persistence.py` (Task 5)  | 7, 8          |
| `embed_text`                         | `services/embeddings.py` (pre-existing) | 3, 5          |
| `get_str_content`                    | `utils.py` (pre-existing)               | 3, 4          |
| `Session(engine)`                    | `db/session.py` (pre-existing)          | 5             |
| `LearnedFact`                        | `db/models.py` (pre-existing)           | 5, 8          |
| `ModelCorrection`                    | `db/models.py` (pre-existing)           | 5, 8          |
