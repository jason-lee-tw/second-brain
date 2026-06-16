# Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete memory system — auto fact extraction, conflict detection, model correction detection, cross-turn state machine, and a full `MemoryRetrievalNode` replacing the stub from Ticket 4.

**Architecture:** `MemoryRetrievalNode` embeds each incoming query and runs two parallel pgvector cosine-similarity searches (learned facts + model corrections) to populate `retrieved_memory` at the start of every turn. After synthesis, `MemoryAgentNode` (claude-haiku-4-5) classifies the user message into one of three cases — normal fact extraction, correction detection, or conflict clarification — and populates `fact_updates` / `correction_updates`. `MemoryPersistenceNode` (tool call, no LLM) then embeds each fact, conflict-checks against existing memory at threshold 0.85, and writes to the DB or surfaces a conflict question to the user.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, SQLModel, asyncpg, pgvector, Anthropic SDK (`claude-haiku-4-5`), Ollama (`qwen3-embedding:0.6b`, dim=1024), pytest + pytest-asyncio, `unittest.mock`.

---

## File Map

| Action   | Path                                                                          | Responsibility                                        |
|----------|-------------------------------------------------------------------------------|-------------------------------------------------------|
| Create   | `apps/backend/src/second_brain/utils/embedding.py`                           | Ollama embedding HTTP helper (shared utility)         |
| Modify   | `apps/backend/src/second_brain/nodes/memory_retrieval.py`                    | Replace stub with real dual-table cosine search       |
| Create   | `apps/backend/src/second_brain/nodes/memory_agent.py`                        | Fact extraction + correction detection (3 cases)      |
| Create   | `apps/backend/src/second_brain/nodes/memory_persistence.py`                  | DB writes + conflict detection + embedding generation |
| Modify   | `apps/backend/src/second_brain/graphs/query_graph.py`                        | Wire memory nodes after `redact_outbound`             |
| Create   | `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py`                | Unit tests for MemoryRetrievalNode                    |
| Create   | `apps/backend/tests/unit/test_nodes/test_memory_agent.py`                    | Unit tests for MemoryAgentNode (all 3 cases)          |
| Create   | `apps/backend/tests/unit/test_nodes/test_memory_persistence.py`              | Unit tests for MemoryPersistenceNode                  |
| Create   | `apps/backend/tests/integration/test_memory_system.py`                       | Integration test: full memory loop                    |

---

### Task 1: Embedding Utility + MemoryRetrievalNode Full Implementation

**Files:**
- Create: `apps/backend/src/second_brain/utils/embedding.py`
- Modify: `apps/backend/src/second_brain/nodes/memory_retrieval.py`
- Test: `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/unit/test_nodes/test_memory_retrieval.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
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
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_memory_retrieval_merges_and_sorts_by_score():
    """MemoryRetrievalNode merges learned_facts + model_corrections, sorted by similarity score."""
    state = _make_state()
    mock_embedding = [0.1] * 1024

    fact_row = MagicMock()
    fact_row.id = "fact-uuid-1"
    fact_row.fact = "The user likes sushi"
    fact_row.confidence = 0.9
    fact_row.score = 0.92

    correction_row = MagicMock()
    correction_row.id = "corr-uuid-1"
    correction_row.fact = "Tokyo is in Japan, not China"
    correction_row.score = 0.85

    with (
        patch("second_brain.nodes.memory_retrieval.get_embedding", return_value=mock_embedding),
        patch("second_brain.nodes.memory_retrieval.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session

        facts_result = MagicMock()
        facts_result.fetchall.return_value = [fact_row]
        corrections_result = MagicMock()
        corrections_result.fetchall.return_value = [correction_row]

        # execute is called twice (facts then corrections, via asyncio.gather)
        mock_session.execute = AsyncMock(side_effect=[facts_result, corrections_result])

        result = await memory_retrieval_node(state)

    memory: list[MemoryItem] = result["retrieved_memory"]
    assert len(memory) == 2
    # Sorted descending by score: 0.92 first
    assert memory[0]["id"] == "fact-uuid-1"
    assert memory[0]["type"] == "learned_fact"
    assert memory[0]["confidence"] == 0.9
    assert memory[1]["id"] == "corr-uuid-1"
    assert memory[1]["type"] == "model_correction"
    assert memory[1]["confidence"] == 1.0  # model_corrections have no stored confidence


@pytest.mark.asyncio
async def test_memory_retrieval_returns_empty_when_db_empty():
    """Returns empty list when no records exist in either table."""
    state = _make_state()

    with (
        patch("second_brain.nodes.memory_retrieval.get_embedding", return_value=[0.0] * 1024),
        patch("second_brain.nodes.memory_retrieval.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=empty_result)

        result = await memory_retrieval_node(state)

    assert result["retrieved_memory"] == []


@pytest.mark.asyncio
async def test_memory_retrieval_uses_last_human_message():
    """Embedding is called with the content of the most recent HumanMessage."""
    from langchain_core.messages import AIMessage

    state = _make_state(
        messages=[
            HumanMessage(content="First question"),
            AIMessage(content="First answer"),
            HumanMessage(content="Second question — this one"),
        ]
    )

    with (
        patch("second_brain.nodes.memory_retrieval.get_embedding", return_value=[0.1] * 1024) as mock_embed,
        patch("second_brain.nodes.memory_retrieval.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        empty = MagicMock()
        empty.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=empty)

        await memory_retrieval_node(state)

    mock_embed.assert_called_once_with("Second question — this one")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'second_brain.nodes.memory_retrieval'` (or the stub returns a stub dict).

- [ ] **Step 3: Create the embedding utility**

```python
# apps/backend/src/second_brain/utils/embedding.py

import os
import httpx

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = "qwen3-embedding:0.6b"


async def get_embedding(text: str) -> list[float]:
    """Embed text via Ollama. Returns a list of 1024 floats."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
        )
        response.raise_for_status()
        return response.json()["embedding"]


def embedding_to_pg_literal(embedding: list[float]) -> str:
    """Convert a list of floats to the '[x,y,...]' string pgvector expects."""
    return f"[{','.join(str(x) for x in embedding)}]"
```

- [ ] **Step 4: Implement MemoryRetrievalNode (replace stub)**

```python
# apps/backend/src/second_brain/nodes/memory_retrieval.py

import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from langchain_core.messages import HumanMessage

from second_brain.graphs.state import SecondBrainState, MemoryItem
from second_brain.utils.embedding import get_embedding, embedding_to_pg_literal

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain",
)

_engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def _last_human_content(messages: list) -> str:
    """Return the content of the most recent HumanMessage."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            return content if isinstance(content, str) else ""
    return ""


async def memory_retrieval_node(state: SecondBrainState) -> dict:
    """
    Embed the current user query and run two parallel cosine-similarity searches:
      1. learned_facts (top-k=5)
      2. model_corrections (top-k=3)
    Merge results, sort by score descending, return as retrieved_memory.
    """
    query_text = _last_human_content(state["messages"])
    embedding = await get_embedding(query_text)
    pg_literal = embedding_to_pg_literal(embedding)

    async def _search_facts(session: AsyncSession) -> list[tuple[float, MemoryItem]]:
        result = await session.execute(
            text(
                """
                SELECT id::text, fact, confidence,
                       1 - (embedding <=> :emb::vector) AS score
                FROM learned_facts
                ORDER BY score DESC
                LIMIT 5
                """
            ),
            {"emb": pg_literal},
        )
        return [
            (
                row.score,
                MemoryItem(id=row.id, fact=row.fact, confidence=row.confidence, type="learned_fact"),
            )
            for row in result.fetchall()
        ]

    async def _search_corrections(session: AsyncSession) -> list[tuple[float, MemoryItem]]:
        result = await session.execute(
            text(
                """
                SELECT id::text, correction AS fact,
                       1 - (embedding <=> :emb::vector) AS score
                FROM model_corrections
                ORDER BY score DESC
                LIMIT 3
                """
            ),
            {"emb": pg_literal},
        )
        return [
            (
                row.score,
                MemoryItem(id=row.id, fact=row.fact, confidence=1.0, type="model_correction"),
            )
            for row in result.fetchall()
        ]

    async with AsyncSessionLocal() as session:
        facts_scored, corrections_scored = await asyncio.gather(
            _search_facts(session),
            _search_corrections(session),
        )

    all_scored = sorted(facts_scored + corrections_scored, key=lambda x: x[0], reverse=True)
    retrieved_memory = [item for _, item in all_scored]

    return {"retrieved_memory": retrieved_memory}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/utils/embedding.py \
        apps/backend/src/second_brain/nodes/memory_retrieval.py \
        apps/backend/tests/unit/test_nodes/test_memory_retrieval.py
git commit -m "feat(memory): implement MemoryRetrievalNode with dual-table cosine search"
```

---

### Task 2: Memory Agent — Case 1: Normal Fact Extraction

**Files:**
- Create: `apps/backend/src/second_brain/nodes/memory_agent.py`
- Create: `apps/backend/tests/unit/test_nodes/test_memory_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/unit/test_nodes/test_memory_agent.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage
from second_brain.nodes.memory_agent import memory_agent_node
from second_brain.graphs.state import SecondBrainState


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
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


def _mock_tool_response(tool_name: str, input_dict: dict) -> MagicMock:
    """Build a mock anthropic Messages response with one tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = input_dict
    response = MagicMock()
    response.content = [block]
    return response


# ── Case 1 tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case1_extracts_user_facts():
    """Case 1: Self-referential facts are extracted and returned as fact_updates."""
    state = _make_state(
        messages=[HumanMessage(content="I work as a software engineer in Berlin.")],
        is_uncertain=False,
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response(
                "extract_facts",
                {"facts": [{"fact": "The user is a software engineer in Berlin.", "confidence": 0.95}]},
            )
        )
        result = await memory_agent_node(state)

    assert len(result["fact_updates"]) == 1
    assert result["fact_updates"][0]["fact"] == "The user is a software engineer in Berlin."
    assert result["fact_updates"][0]["confidence"] == 0.95
    assert result["fact_updates"][0]["conflicts_with"] == []
    assert result["correction_updates"] == []


@pytest.mark.asyncio
async def test_case1_no_facts_in_generic_message():
    """Case 1: Message with no self-referential content returns empty fact_updates."""
    state = _make_state(
        messages=[HumanMessage(content="What is the tallest mountain?")],
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response("extract_facts", {"facts": []})
        )
        result = await memory_agent_node(state)

    assert result["fact_updates"] == []
    assert result["correction_updates"] == []


@pytest.mark.asyncio
async def test_case1_sets_awaiting_correction_when_uncertain():
    """Case 1: is_uncertain=True in state → awaiting_correction=True in output."""
    state = _make_state(
        messages=[HumanMessage(content="What's the capital of France?")],
        is_uncertain=True,  # synthesis was uncertain this turn
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response("extract_facts", {"facts": []})
        )
        result = await memory_agent_node(state)

    assert result.get("awaiting_correction") is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'second_brain.nodes.memory_agent'`

- [ ] **Step 3: Create memory_agent.py with Case 1**

```python
# apps/backend/src/second_brain/nodes/memory_agent.py

from __future__ import annotations

from typing import Any

import anthropic
from langchain_core.messages import HumanMessage, AIMessage

from second_brain.graphs.state import SecondBrainState, FactUpdate, CorrectionUpdate

client = anthropic.AsyncAnthropic()

# ── Tool schemas ───────────────────────────────────────────────────────────────

_EXTRACT_FACTS_TOOL: dict = {
    "name": "extract_facts",
    "description": (
        "Extract self-referential facts from the user's message. "
        "A fact is any statement where the user explicitly says something about themselves "
        "(e.g. 'I work as X', 'I live in Y', 'I prefer Z'). "
        "Rephrase each fact as a third-person statement about the user."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["fact", "confidence"],
                },
            }
        },
        "required": ["facts"],
    },
}

_CLASSIFY_CORRECTION_TOOL: dict = {
    "name": "classify_message",
    "description": (
        "Classify whether the user's message is a correction of the AI's previous uncertain answer, "
        "or an unrelated new query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_correction": {
                "type": "boolean",
                "description": "True if the message corrects the prior answer; False if it is a new query.",
            },
            "correction": {
                "type": "string",
                "description": "The corrected fact/answer (only when is_correction=True).",
            },
            "root_cause": {
                "type": "string",
                "description": "Why the AI was wrong (e.g. 'AI confused X with Y') (only when is_correction=True).",
            },
        },
        "required": ["is_correction"],
    },
}

_RESOLVE_CONFLICT_TOOL: dict = {
    "name": "resolve_conflict",
    "description": "Parse the user's clarification instruction to resolve a memory conflict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["keep_new", "keep_existing", "keep_both"],
                "description": "What to do: keep_new replaces old, keep_existing discards new, keep_both stores both.",
            },
            "resolved_fact": {
                "type": "string",
                "description": "The final fact text to store (empty string when action is keep_existing).",
            },
            "confidence": {"type": "number"},
        },
        "required": ["action", "resolved_fact", "confidence"],
    },
}


# ── Message helpers ────────────────────────────────────────────────────────────

def _last_human_content(messages: list) -> str:
    """Content of the most recent HumanMessage."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            return content if isinstance(content, str) else ""
    return ""


def _prior_ai_content(messages: list) -> str:
    """Content of the AIMessage immediately before the last HumanMessage."""
    last_human_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break
    if last_human_idx is None or last_human_idx == 0:
        return ""
    for i in range(last_human_idx - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            content = messages[i].content
            return content if isinstance(content, str) else ""
    return ""


# ── LLM helpers ───────────────────────────────────────────────────────────────

async def _extract_facts(user_message: str) -> list[FactUpdate]:
    response = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        tools=[_EXTRACT_FACTS_TOOL],
        tool_choice={"type": "any"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract any self-referential facts from this message. "
                    "Return an empty list if none exist.\n\n"
                    f"User message: {user_message}"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_facts":
            return [
                FactUpdate(fact=f["fact"], confidence=f["confidence"], conflicts_with=[])
                for f in block.input["facts"]
            ]
    return []


async def _classify_correction(
    user_message: str, prior_answer: str
) -> tuple[bool, CorrectionUpdate | None]:
    response = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        tools=[_CLASSIFY_CORRECTION_TOOL],
        tool_choice={"type": "any"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"The AI gave an uncertain answer: {prior_answer!r}\n\n"
                    f"The user then said: {user_message!r}\n\n"
                    "Is the user correcting the AI's answer, or starting a new unrelated query?"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_message":
            inp = block.input
            if inp["is_correction"]:
                correction = CorrectionUpdate(
                    original_answer=prior_answer,
                    correction=inp.get("correction", user_message),
                    root_cause=inp.get("root_cause", "Unknown root cause"),
                )
                return True, correction
            return False, None
    return False, None


async def _resolve_conflict(
    user_message: str,
    conflict_context: list[str],
    pending_fact_updates: list[FactUpdate],
) -> list[FactUpdate]:
    # Collect all conflicting IDs from the pending facts so we can mark resolved facts as pre-resolved
    all_conflict_ids: list[str] = []
    for fu in pending_fact_updates:
        all_conflict_ids.extend(fu.get("conflicts_with", []))

    response = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        tools=[_RESOLVE_CONFLICT_TOOL],
        tool_choice={"type": "any"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Context:\n" + "\n".join(conflict_context) + "\n\n"
                    f"User instruction: {user_message!r}\n\n"
                    "Parse the user's instruction to resolve the memory conflict."
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "resolve_conflict":
            inp = block.input
            if inp["action"] == "keep_existing":
                return []
            # Mark conflicts_with with the existing IDs so MemoryPersistenceNode
            # skips conflict re-check and writes directly.
            return [
                FactUpdate(
                    fact=inp["resolved_fact"],
                    confidence=inp["confidence"],
                    conflicts_with=all_conflict_ids,
                )
            ]
    # Fallback: keep pending if LLM didn't return expected tool use
    return []


# ── Node entry point ───────────────────────────────────────────────────────────

async def memory_agent_node(state: SecondBrainState) -> dict[str, Any]:
    """
    Three cases based on state:
      Case 1 (default): Extract self-referential facts from user message.
      Case 2 (awaiting_correction=True): Classify as correction or new query.
      Case 3 (awaiting_conflict_clarification=True): Resolve a previously surfaced conflict.
    """
    messages = state["messages"]
    awaiting_correction: bool = state.get("awaiting_correction", False)
    awaiting_conflict: bool = state.get("awaiting_conflict_clarification", False)
    is_uncertain: bool = state.get("is_uncertain", False)

    user_message = _last_human_content(messages)
    updates: dict[str, Any] = {"fact_updates": [], "correction_updates": []}

    if awaiting_conflict:
        # Case 3: User is clarifying a conflict surfaced in the previous turn
        resolved = await _resolve_conflict(
            user_message,
            state.get("conflict_context", []),
            state.get("fact_updates", []),
        )
        updates["fact_updates"] = resolved
        updates["awaiting_conflict_clarification"] = False
        updates["conflict_context"] = []

    elif awaiting_correction:
        # Case 2: Was the user correcting an uncertain prior answer?
        prior_answer = _prior_ai_content(messages)
        is_correction, correction_update = await _classify_correction(user_message, prior_answer)
        updates["awaiting_correction"] = False  # always reset

        if is_correction and correction_update:
            updates["correction_updates"] = [correction_update]
        else:
            # Treat as a normal new query
            facts = await _extract_facts(user_message)
            updates["fact_updates"] = facts
            if is_uncertain:
                updates["awaiting_correction"] = True

    else:
        # Case 1: Normal turn — extract facts
        facts = await _extract_facts(user_message)
        updates["fact_updates"] = facts
        if is_uncertain:
            updates["awaiting_correction"] = True

    return updates
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_agent.py \
        apps/backend/tests/unit/test_nodes/test_memory_agent.py
git commit -m "feat(memory): add MemoryAgentNode Case 1 — fact extraction"
```

---

### Task 3: Memory Agent — Case 2: Correction Detection + awaiting_correction State Machine (AC-3)

**Files:**
- Modify: `apps/backend/tests/unit/test_nodes/test_memory_agent.py` (add tests)
- No implementation changes — Case 2 is already in `memory_agent.py` from Task 2.

- [ ] **Step 1: Write the failing tests**

Add these tests to `apps/backend/tests/unit/test_nodes/test_memory_agent.py`:

```python
# ── Case 2 tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case2_resets_awaiting_correction_on_unrelated_query():
    """AC-3: awaiting_correction=True + unrelated query → awaiting_correction=False, no corrections stored."""
    state = _make_state(
        messages=[
            AIMessage(content="I think the capital of France is Lyon, but I'm not sure."),
            HumanMessage(content="What time is it in Tokyo?"),  # completely unrelated
        ],
        awaiting_correction=True,
        is_uncertain=False,
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        # Classify as NOT a correction
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response("classify_message", {"is_correction": False})
        )
        result = await memory_agent_node(state)

    assert result["awaiting_correction"] is False
    assert result["correction_updates"] == []


@pytest.mark.asyncio
async def test_case2_extracts_correction_when_user_corrects():
    """Case 2: user corrects uncertain answer → correction_updates populated, awaiting_correction=False."""
    state = _make_state(
        messages=[
            AIMessage(content="I think the capital of France is Lyon, but I'm not sure."),
            HumanMessage(content="Actually it's Paris, not Lyon."),
        ],
        awaiting_correction=True,
        is_uncertain=False,
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response(
                "classify_message",
                {
                    "is_correction": True,
                    "correction": "The capital of France is Paris.",
                    "root_cause": "AI confused Lyon with Paris.",
                },
            )
        )
        result = await memory_agent_node(state)

    assert result["awaiting_correction"] is False
    assert len(result["correction_updates"]) == 1
    c = result["correction_updates"][0]
    assert c["correction"] == "The capital of France is Paris."
    assert c["root_cause"] == "AI confused Lyon with Paris."
    # original_answer is the AI's prior uncertain message (messages[-2] before HumanMessage)
    assert "Lyon" in c["original_answer"]


@pytest.mark.asyncio
async def test_case2_non_correction_still_extracts_facts():
    """Case 2: unrelated query → fact extraction still runs (user might say something about themselves)."""
    state = _make_state(
        messages=[
            AIMessage(content="I'm not sure about this."),
            HumanMessage(content="I actually live in Berlin. Anyway, what's the weather?"),
        ],
        awaiting_correction=True,
        is_uncertain=False,
    )

    classify_response = _mock_tool_response("classify_message", {"is_correction": False})
    extract_response = _mock_tool_response(
        "extract_facts",
        {"facts": [{"fact": "The user lives in Berlin.", "confidence": 0.9}]},
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=[classify_response, extract_response])
        result = await memory_agent_node(state)

    assert result["awaiting_correction"] is False
    assert len(result["fact_updates"]) == 1
    assert "Berlin" in result["fact_updates"][0]["fact"]


@pytest.mark.asyncio
async def test_case2_does_not_set_awaiting_correction_when_not_uncertain():
    """Case 2: not a correction + this turn not uncertain → awaiting_correction stays False."""
    state = _make_state(
        messages=[
            AIMessage(content="I'm unsure about this."),
            HumanMessage(content="What's 2+2?"),
        ],
        awaiting_correction=True,
        is_uncertain=False,  # this turn's synthesis was confident
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        classify_response = _mock_tool_response("classify_message", {"is_correction": False})
        extract_response = _mock_tool_response("extract_facts", {"facts": []})
        mock_client.messages.create = AsyncMock(side_effect=[classify_response, extract_response])
        result = await memory_agent_node(state)

    assert result.get("awaiting_correction") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v -k "case2"
```

Expected: `FAILED` — tests were collected but the helper `_mock_tool_response` is already in the file, and `memory_agent_node` exists. These should actually pass if Case 2 was already implemented in Task 2. Confirm all 4 new Case 2 tests pass.

- [ ] **Step 3: Run all memory agent tests**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v
```

Expected: `7 passed` (3 from Task 2 + 4 new Case 2 tests)

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_nodes/test_memory_agent.py
git commit -m "test(memory): add Case 2 correction detection + AC-3 state machine tests"
```

---

### Task 4: Memory Agent — Case 3: Conflict Clarification Handling

**Files:**
- Modify: `apps/backend/tests/unit/test_nodes/test_memory_agent.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Add these tests to `apps/backend/tests/unit/test_nodes/test_memory_agent.py`:

```python
# ── Case 3 tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case3_resolves_conflict_keep_new():
    """Case 3: keep_new → returns resolved fact with conflicts_with populated (marks as user-resolved)."""
    state = _make_state(
        messages=[HumanMessage(content="Use the new one — I moved to Tokyo last month.")],
        awaiting_conflict_clarification=True,
        conflict_context=["Existing: \"User lives in Berlin\" | New: \"User lives in Tokyo\""],
        fact_updates=[
            {"fact": "User lives in Tokyo", "confidence": 0.9, "conflicts_with": ["existing-id-1"]},
        ],
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response(
                "resolve_conflict",
                {"action": "keep_new", "resolved_fact": "User lives in Tokyo", "confidence": 0.95},
            )
        )
        result = await memory_agent_node(state)

    assert result["awaiting_conflict_clarification"] is False
    assert result["conflict_context"] == []
    assert len(result["fact_updates"]) == 1
    resolved = result["fact_updates"][0]
    assert resolved["fact"] == "User lives in Tokyo"
    assert resolved["confidence"] == 0.95
    # conflicts_with carries the original conflict IDs so persistence skips re-checking
    assert "existing-id-1" in resolved["conflicts_with"]


@pytest.mark.asyncio
async def test_case3_resolves_conflict_keep_existing():
    """Case 3: keep_existing → returns empty fact_updates (nothing to write)."""
    state = _make_state(
        messages=[HumanMessage(content="Keep the old one, the new fact was a mistake.")],
        awaiting_conflict_clarification=True,
        conflict_context=["Existing: \"User lives in Berlin\" | New: \"User lives in Tokyo\""],
        fact_updates=[
            {"fact": "User lives in Tokyo", "confidence": 0.9, "conflicts_with": ["existing-id-1"]},
        ],
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response(
                "resolve_conflict",
                {"action": "keep_existing", "resolved_fact": "", "confidence": 1.0},
            )
        )
        result = await memory_agent_node(state)

    assert result["awaiting_conflict_clarification"] is False
    assert result["fact_updates"] == []


@pytest.mark.asyncio
async def test_case3_does_not_touch_awaiting_correction():
    """Case 3: awaiting_correction state is left unchanged."""
    state = _make_state(
        messages=[HumanMessage(content="Keep the new one.")],
        awaiting_conflict_clarification=True,
        awaiting_correction=False,
        conflict_context=["Existing: \"A\" | New: \"B\""],
        fact_updates=[{"fact": "B", "confidence": 0.9, "conflicts_with": ["id-1"]}],
    )

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(
            return_value=_mock_tool_response(
                "resolve_conflict",
                {"action": "keep_new", "resolved_fact": "B", "confidence": 0.9},
            )
        )
        result = await memory_agent_node(state)

    # awaiting_correction must not appear in result (or be False — it must not be set True spuriously)
    assert result.get("awaiting_correction", False) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v -k "case3"
```

Expected: `FAILED` — these tests are new; they should pass if Case 3 was already implemented in `memory_agent.py`. If they fail, check that `_resolve_conflict` is wired into `memory_agent_node`. Confirm all 3 pass.

- [ ] **Step 3: Run all memory agent tests**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_agent.py -v
```

Expected: `10 passed` (7 from Tasks 2–3 + 3 new Case 3 tests)

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/unit/test_nodes/test_memory_agent.py
git commit -m "test(memory): add Case 3 conflict clarification tests for MemoryAgentNode"
```

---

### Task 5: MemoryPersistenceNode — Fact Persistence + Conflict Detection (AC-1, AC-2)

**Files:**
- Create: `apps/backend/src/second_brain/nodes/memory_persistence.py`
- Create: `apps/backend/tests/unit/test_nodes/test_memory_persistence.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_memory_persistence.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from langchain_core.messages import HumanMessage
from second_brain.nodes.memory_persistence import memory_persistence_node
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
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


# ── AC-1: fact written to DB ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac1_writes_fact_with_embedding():
    """AC-1: After fact extraction, learned_facts table receives the fact with a valid embedding."""
    state = _make_state(
        fact_updates=[{"fact": "The user is a vegetarian.", "confidence": 0.9, "conflicts_with": []}],
        correction_updates=[],
    )
    mock_embedding = [0.5] * 1024

    with (
        patch("second_brain.nodes.memory_persistence.get_embedding", return_value=mock_embedding),
        patch("second_brain.nodes.memory_persistence.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session

        # Conflict check returns no conflicts
        no_conflict = MagicMock()
        no_conflict.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=no_conflict)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        result = await memory_persistence_node(state)

    # Verify a record was added and committed
    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.fact == "The user is a vegetarian."
    assert added.confidence == 0.9
    assert added.embedding == mock_embedding
    assert len(added.embedding) == 1024
    assert added.source_session == "test-session"

    assert result.get("awaiting_conflict_clarification") is False
    assert result.get("fact_updates") == []


@pytest.mark.asyncio
async def test_ac1_skips_conflict_check_when_conflicts_with_is_set():
    """AC-1 (user-resolved): conflicts_with populated → write directly, no conflict check."""
    state = _make_state(
        fact_updates=[
            {"fact": "User lives in Tokyo", "confidence": 0.95, "conflicts_with": ["old-id"]}
        ],
        correction_updates=[],
    )
    mock_embedding = [0.3] * 1024

    with (
        patch("second_brain.nodes.memory_persistence.get_embedding", return_value=mock_embedding),
        patch("second_brain.nodes.memory_persistence.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        result = await memory_persistence_node(state)

    # execute (conflict check) must NOT be called
    mock_session.execute.assert_not_called()
    # But add + commit must be called
    mock_session.add.assert_called_once()


# ── AC-2: conflict detection ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac2_detects_conflict_and_sets_state():
    """AC-2: Conflicting fact → awaiting_conflict_clarification=True, fact NOT written."""
    state = _make_state(
        final_answer="You mentioned moving to Tokyo.",
        fact_updates=[
            {"fact": "User lives in Tokyo", "confidence": 0.9, "conflicts_with": []}
        ],
        correction_updates=[],
    )
    mock_embedding = [0.5] * 1024

    conflict_row = MagicMock()
    conflict_row.id = "existing-fact-id"
    conflict_row.score = 0.92

    existing_row = MagicMock()
    existing_row.fact = "User lives in Berlin"

    with (
        patch("second_brain.nodes.memory_persistence.get_embedding", return_value=mock_embedding),
        patch("second_brain.nodes.memory_persistence.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session

        conflict_result = MagicMock()
        conflict_result.fetchall.return_value = [conflict_row]
        existing_result = MagicMock()
        existing_result.fetchone.return_value = existing_row

        # First execute = conflict check, second = fetch existing fact text
        mock_session.execute = AsyncMock(side_effect=[conflict_result, existing_result])
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        result = await memory_persistence_node(state)

    # Must NOT write
    mock_session.add.assert_not_called()

    assert result["awaiting_conflict_clarification"] is True
    assert len(result["conflict_context"]) == 1
    assert "Berlin" in result["conflict_context"][0]
    assert "Tokyo" in result["conflict_context"][0]

    # Conflict message appended to final_answer
    assert "⚠️" in result["final_answer"]
    assert "Berlin" in result["final_answer"]
    assert "Tokyo" in result["final_answer"]

    # Pending fact preserved with conflicting IDs so next turn can resolve
    assert len(result["fact_updates"]) == 1
    assert "existing-fact-id" in result["fact_updates"][0]["conflicts_with"]


@pytest.mark.asyncio
async def test_no_conflict_clears_fact_updates():
    """After successful persistence, fact_updates is cleared."""
    state = _make_state(
        fact_updates=[{"fact": "User loves hiking.", "confidence": 0.85, "conflicts_with": []}],
        correction_updates=[],
    )

    with (
        patch("second_brain.nodes.memory_persistence.get_embedding", return_value=[0.1] * 1024),
        patch("second_brain.nodes.memory_persistence.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        no_conflict = MagicMock()
        no_conflict.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=no_conflict)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        result = await memory_persistence_node(state)

    assert result.get("fact_updates") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_persistence.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'second_brain.nodes.memory_persistence'`

- [ ] **Step 3: Implement MemoryPersistenceNode (facts only)**

```python
# apps/backend/src/second_brain/nodes/memory_persistence.py

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from second_brain.db.models import LearnedFact, ModelCorrection
from second_brain.graphs.state import SecondBrainState, FactUpdate, CorrectionUpdate
from second_brain.utils.embedding import get_embedding, embedding_to_pg_literal

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain",
)

_engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

CONFLICT_THRESHOLD = 0.85


async def _check_conflict(session: AsyncSession, pg_literal: str) -> list[str]:
    """Return IDs of existing learned_facts whose similarity exceeds CONFLICT_THRESHOLD."""
    result = await session.execute(
        text(
            """
            SELECT id::text, 1 - (embedding <=> :emb::vector) AS score
            FROM learned_facts
            WHERE 1 - (embedding <=> :emb::vector) > :threshold
            ORDER BY score DESC
            """
        ),
        {"emb": pg_literal, "threshold": CONFLICT_THRESHOLD},
    )
    return [row.id for row in result.fetchall()]


async def _fetch_fact_text(session: AsyncSession, fact_id: str) -> str:
    result = await session.execute(
        text("SELECT fact FROM learned_facts WHERE id::text = :id"),
        {"id": fact_id},
    )
    row = result.fetchone()
    return row.fact if row else ""


async def _persist_fact(
    session: AsyncSession,
    fact_update: FactUpdate,
    session_id: str,
) -> tuple[bool, list[str], str]:
    """
    Returns (wrote: bool, conflicting_ids: list[str], existing_fact_text: str).

    If fact_update.conflicts_with is non-empty the user already resolved the conflict —
    write directly without re-checking.
    If a conflict is found (score > CONFLICT_THRESHOLD) return without writing.
    Otherwise write and return (True, [], "").
    """
    embedding = await get_embedding(fact_update["fact"])
    pg_literal = embedding_to_pg_literal(embedding)

    # User already resolved — skip conflict check
    if fact_update["conflicts_with"]:
        record = LearnedFact(
            id=uuid.uuid4(),
            fact=fact_update["fact"],
            embedding=embedding,
            source_session=session_id,
            confidence=fact_update["confidence"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(record)
        await session.commit()
        return True, [], ""

    conflicting_ids = await _check_conflict(session, pg_literal)
    if conflicting_ids:
        existing_fact = await _fetch_fact_text(session, conflicting_ids[0])
        return False, conflicting_ids, existing_fact

    record = LearnedFact(
        id=uuid.uuid4(),
        fact=fact_update["fact"],
        embedding=embedding,
        source_session=session_id,
        confidence=fact_update["confidence"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(record)
    await session.commit()
    return True, [], ""


async def memory_persistence_node(state: SecondBrainState) -> dict[str, Any]:
    """
    Tool-call node (no LLM).
    - For each FactUpdate: embed, conflict-check, write or surface conflict.
    - For each CorrectionUpdate: embed correction text, write to model_corrections.
    """
    fact_updates: list[FactUpdate] = state.get("fact_updates", [])
    correction_updates: list[CorrectionUpdate] = state.get("correction_updates", [])
    session_id: str = state["session_id"]
    final_answer: str = state.get("final_answer", "")

    conflict_detected = False
    conflict_contexts: list[str] = []
    pending_fact_updates: list[FactUpdate] = []

    async with AsyncSessionLocal() as session:
        for fact_update in fact_updates:
            wrote, conflicting_ids, existing_fact = await _persist_fact(
                session, fact_update, session_id
            )
            if not wrote and conflicting_ids:
                conflict_detected = True
                conflict_contexts.append(
                    f"Existing: \"{existing_fact}\" | New: \"{fact_update['fact']}\""
                )
                conflict_msg = (
                    f"\n\n⚠️ I noticed a potential conflict with existing memory:\n"
                    f"- Existing: \"{existing_fact}\"\n"
                    f"- New: \"{fact_update['fact']}\"\n"
                    f"Please clarify which is correct (or if both apply)."
                )
                final_answer = final_answer + conflict_msg
                # Preserve the fact with conflict IDs so MemoryAgent Case 3 can resolve it
                pending_fact_updates.append(
                    FactUpdate(
                        fact=fact_update["fact"],
                        confidence=fact_update["confidence"],
                        conflicts_with=conflicting_ids,
                    )
                )

        for correction in correction_updates:
            await _persist_correction(session, correction, session_id)

    result: dict[str, Any] = {
        "awaiting_conflict_clarification": conflict_detected,
        "conflict_context": conflict_contexts,
    }

    if conflict_detected:
        result["final_answer"] = final_answer
        result["fact_updates"] = pending_fact_updates
    else:
        result["fact_updates"] = []

    return result


async def _persist_correction(
    session: AsyncSession,
    correction: CorrectionUpdate,
    session_id: str,
) -> None:
    """Embed the correction text and write to model_corrections. (Implemented in Task 6.)"""
    pass  # placeholder — Task 6 fills this in
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_persistence.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_persistence.py \
        apps/backend/tests/unit/test_nodes/test_memory_persistence.py
git commit -m "feat(memory): add MemoryPersistenceNode — fact persistence + conflict detection (AC-1, AC-2)"
```

---

### Task 6: MemoryPersistenceNode — Correction Persistence with Embedding (AC-4)

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/memory_persistence.py` (fill in `_persist_correction`)
- Modify: `apps/backend/tests/unit/test_nodes/test_memory_persistence.py` (add AC-4 tests)

- [ ] **Step 1: Write the failing test**

Add these tests to `apps/backend/tests/unit/test_nodes/test_memory_persistence.py`:

```python
# ── AC-4: correction persistence ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ac4_writes_correction_with_embedding():
    """AC-4: correction_updates → model_corrections row with root_cause + embedding."""
    state = _make_state(
        fact_updates=[],
        correction_updates=[
            {
                "original_answer": "The capital of France is Lyon.",
                "correction": "The capital of France is Paris.",
                "root_cause": "AI confused Lyon with Paris.",
            }
        ],
    )
    mock_embedding = [0.3] * 1024

    with (
        patch("second_brain.nodes.memory_persistence.get_embedding", return_value=mock_embedding),
        patch("second_brain.nodes.memory_persistence.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        result = await memory_persistence_node(state)

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]

    # Verify it is a ModelCorrection, not a LearnedFact
    from second_brain.db.models import ModelCorrection
    assert isinstance(added, ModelCorrection)

    assert added.correction == "The capital of France is Paris."
    assert added.original_answer == "The capital of France is Lyon."
    assert added.root_cause == "AI confused Lyon with Paris."
    assert added.embedding == mock_embedding
    assert len(added.embedding) == 1024
    assert added.source_session == "test-session"


@pytest.mark.asyncio
async def test_ac4_embeds_correction_text_not_original_answer():
    """AC-4: get_embedding is called with the correction text, not original_answer."""
    state = _make_state(
        fact_updates=[],
        correction_updates=[
            {
                "original_answer": "Wrong answer here",
                "correction": "Correct answer here",
                "root_cause": "Some root cause",
            }
        ],
    )

    with (
        patch("second_brain.nodes.memory_persistence.get_embedding", return_value=[0.1] * 1024) as mock_embed,
        patch("second_brain.nodes.memory_persistence.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        await memory_persistence_node(state)

    # Embedding must be called with the correction string, not original_answer
    mock_embed.assert_called_once_with("Correct answer here")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_persistence.py::test_ac4_writes_correction_with_embedding \
    tests/unit/test_nodes/test_memory_persistence.py::test_ac4_embeds_correction_text_not_original_answer -v
```

Expected: `FAILED` — `_persist_correction` is a no-op placeholder.

- [ ] **Step 3: Implement `_persist_correction`**

Replace the placeholder `_persist_correction` in `apps/backend/src/second_brain/nodes/memory_persistence.py`:

```python
async def _persist_correction(
    session: AsyncSession,
    correction: CorrectionUpdate,
    session_id: str,
) -> None:
    """Embed the `correction` field and write a ModelCorrection row."""
    embedding = await get_embedding(correction["correction"])
    record = ModelCorrection(
        id=uuid.uuid4(),
        original_answer=correction["original_answer"],
        correction=correction["correction"],
        root_cause=correction["root_cause"],
        embedding=embedding,
        source_session=session_id,
        created_at=datetime.utcnow(),
    )
    session.add(record)
    await session.commit()
```

- [ ] **Step 4: Run all persistence tests**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_memory_persistence.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_persistence.py \
        apps/backend/tests/unit/test_nodes/test_memory_persistence.py
git commit -m "feat(memory): implement correction persistence with embedding (AC-4)"
```

---

### Task 7: Wire Memory Nodes into Query Graph

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/query_graph.py`

Context: By the end of Ticket 4, `query_graph.py` has a graph with nodes including `redact_outbound`, which feeds directly into `END`. This task inserts `memory_agent` and `memory_persistence` between `redact_outbound` and `END`.

- [ ] **Step 1: Read the current edge from redact_outbound to END**

```bash
grep -n "redact_outbound\|memory_agent\|memory_persistence\|add_edge\|add_node" \
    apps/backend/src/second_brain/graphs/query_graph.py
```

Note the exact line numbers. The changes below target the pattern where `redact_outbound` leads to `END`.

- [ ] **Step 2: Add imports**

At the top of `apps/backend/src/second_brain/graphs/query_graph.py`, add:

```python
from second_brain.nodes.memory_agent import memory_agent_node
from second_brain.nodes.memory_persistence import memory_persistence_node
```

- [ ] **Step 3: Register the new nodes and rewire edges**

In the graph builder function (typically `build_query_graph()` or `create_graph()`), add the two new nodes and update edges. Find the existing `graph.add_edge("redact_outbound", END)` line and replace:

```python
# BEFORE (remove this line):
# graph.add_edge("redact_outbound", END)

# AFTER (add these lines):
graph.add_node("memory_agent", memory_agent_node)
graph.add_node("memory_persistence", memory_persistence_node)

graph.add_edge("redact_outbound", "memory_agent")
graph.add_edge("memory_agent", "memory_persistence")
graph.add_edge("memory_persistence", END)
```

- [ ] **Step 4: Verify the graph compiles without errors**

```bash
cd apps/backend && python -c "
from second_brain.graphs.query_graph import build_query_graph
g = build_query_graph()
print('Graph nodes:', list(g.nodes))
print('OK')
"
```

Expected output contains `memory_agent` and `memory_persistence` in the nodes list.

- [ ] **Step 5: Run the full unit test suite to confirm nothing is broken**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/graphs/query_graph.py
git commit -m "feat(memory): wire MemoryAgentNode + MemoryPersistenceNode into query graph"
```

---

### Task 8: Integration Test — Full Memory Loop

**Files:**
- Create: `apps/backend/tests/integration/test_memory_system.py`

**Pre-condition:** The Docker stack must be running (`docker compose up -d`) with a live PostgreSQL+pgvector instance and Ollama. Integration tests are skipped automatically when `TEST_DATABASE_URL` is unset.

- [ ] **Step 1: Write the integration tests**

```python
# apps/backend/tests/integration/test_memory_system.py
"""
Integration tests for the full memory cycle.
Requires: Docker stack running (PostgreSQL + pgvector + Ollama).
Set TEST_DATABASE_URL to run; tests are skipped otherwise.

Run:
  TEST_DATABASE_URL=postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain_test \
    pytest tests/integration/test_memory_system.py -v -m integration
"""

import os
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from langchain_core.messages import HumanMessage, AIMessage

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as requiring live services")


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set — skipping integration tests")
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.fixture(autouse=True)
async def clean_memory_tables(db_session):
    """Delete test rows before each test to avoid cross-test pollution."""
    test_session_id = "integration-test-session"
    await db_session.execute(
        text("DELETE FROM learned_facts WHERE source_session = :sid"),
        {"sid": test_session_id},
    )
    await db_session.execute(
        text("DELETE FROM model_corrections WHERE source_session = :sid"),
        {"sid": test_session_id},
    )
    await db_session.commit()
    yield


def _make_state(**overrides):
    from second_brain.graphs.state import SecondBrainState
    base: SecondBrainState = {
        "session_id": "integration-test-session",
        "messages": [],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "Test answer.",
        "confidence": 0.9,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ac1_fact_written_to_db_with_embedding(db_session):
    """AC-1: Fact extracted → row in learned_facts with a 1024-dim non-zero embedding."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        messages=[HumanMessage(content="I am a vegetarian and I love hiking.")],
        fact_updates=[
            {"fact": "The user is a vegetarian.", "confidence": 0.95, "conflicts_with": []},
            {"fact": "The user loves hiking.", "confidence": 0.9, "conflicts_with": []},
        ],
    )

    await memory_persistence_node(state)

    result = await db_session.execute(
        text(
            "SELECT fact, confidence, embedding "
            "FROM learned_facts WHERE source_session = :sid"
        ),
        {"sid": "integration-test-session"},
    )
    rows = result.fetchall()
    assert len(rows) == 2

    for row in rows:
        assert row.embedding is not None
        assert len(row.embedding) == 1024
        assert any(x != 0.0 for x in row.embedding), "Embedding must be non-zero"


@pytest.mark.asyncio
async def test_ac2_conflict_detected_sets_flag(db_session):
    """AC-2: Pre-seed a fact, then try to add a conflicting one → awaiting_conflict_clarification=True."""
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.utils.embedding import get_embedding

    # Seed an existing fact directly (bypassing conflict check)
    embedding = await get_embedding("The user lives in Berlin.")
    from second_brain.db.models import LearnedFact
    import uuid
    from datetime import datetime
    seed = LearnedFact(
        id=uuid.uuid4(),
        fact="The user lives in Berlin.",
        embedding=embedding,
        source_session="integration-test-session",
        confidence=0.9,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(seed)
    await db_session.commit()

    # Now try to add a semantically similar (conflicting) fact
    state = _make_state(
        final_answer="You mentioned moving.",
        fact_updates=[
            {"fact": "The user lives in Berlin now.", "confidence": 0.85, "conflicts_with": []}
        ],
    )

    result = await memory_persistence_node(state)

    assert result["awaiting_conflict_clarification"] is True
    assert len(result["conflict_context"]) >= 1
    assert "⚠️" in result["final_answer"]

    # Conflicting fact must NOT have been written
    count_result = await db_session.execute(
        text(
            "SELECT count(*) FROM learned_facts "
            "WHERE source_session = :sid AND fact LIKE '%now%'"
        ),
        {"sid": "integration-test-session"},
    )
    assert count_result.scalar() == 0


@pytest.mark.asyncio
async def test_ac3_unrelated_query_resets_awaiting_correction():
    """AC-3: awaiting_correction=True + unrelated query → awaiting_correction=False."""
    from unittest.mock import patch, AsyncMock, MagicMock
    from second_brain.nodes.memory_agent import memory_agent_node

    state = _make_state(
        messages=[
            AIMessage(content="I think the speed of light is 100 km/s, but I'm not sure."),
            HumanMessage(content="What day is it today?"),  # unrelated
        ],
        awaiting_correction=True,
        is_uncertain=False,
    )

    # Mock LLM call — classify as not a correction
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "classify_message"
    mock_block.input = {"is_correction": False}
    mock_response = MagicMock()
    mock_response.content = [mock_block]

    with patch("second_brain.nodes.memory_agent.client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await memory_agent_node(state)

    assert result["awaiting_correction"] is False
    assert result["correction_updates"] == []


@pytest.mark.asyncio
async def test_ac4_correction_written_with_embedding(db_session):
    """AC-4: correction_updates → model_corrections row with root_cause, correction, 1024-dim embedding."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[],
        correction_updates=[
            {
                "original_answer": "The speed of light is 100 km/s.",
                "correction": "The speed of light is approximately 299,792 km/s.",
                "root_cause": "AI used an incorrect value for the speed of light.",
            }
        ],
    )

    await memory_persistence_node(state)

    result = await db_session.execute(
        text(
            "SELECT correction, root_cause, embedding "
            "FROM model_corrections WHERE source_session = :sid"
        ),
        {"sid": "integration-test-session"},
    )
    rows = result.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert "299,792" in row.correction
    assert row.root_cause == "AI used an incorrect value for the speed of light."
    assert row.embedding is not None
    assert len(row.embedding) == 1024
    assert any(x != 0.0 for x in row.embedding)


@pytest.mark.asyncio
async def test_full_memory_loop_extract_then_retrieve(db_session):
    """
    Full loop:
    1. Persist a user fact.
    2. Run MemoryRetrievalNode on a related query.
    3. Verify the fact appears in retrieved_memory.
    """
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.nodes.memory_retrieval import memory_retrieval_node

    # Turn 1: persist fact
    turn1_state = _make_state(
        fact_updates=[
            {"fact": "The user is a professional cyclist.", "confidence": 0.9, "conflicts_with": []}
        ],
        correction_updates=[],
    )
    await memory_persistence_node(turn1_state)

    # Turn 2: retrieve on related query
    turn2_state = _make_state(
        messages=[HumanMessage(content="What sports do I do?")]
    )
    retrieval_result = await memory_retrieval_node(turn2_state)

    retrieved = retrieval_result["retrieved_memory"]
    assert len(retrieved) >= 1
    facts_text = " ".join(item["fact"] for item in retrieved)
    assert "cyclist" in facts_text.lower()
```

- [ ] **Step 2: Run unit tests to confirm they still pass (integration tests skip without TEST_DATABASE_URL)**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all unit tests pass.

- [ ] **Step 3: Run integration tests (requires Docker stack)**

```bash
cd apps/backend && \
  TEST_DATABASE_URL=postgresql+asyncpg://second_brain:second_brain@localhost:5432/second_brain_test \
  python -m pytest tests/integration/test_memory_system.py -v -m integration
```

Expected: `5 passed` (all AC-1 through AC-4 + full loop).

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/test_memory_system.py
git commit -m "test(memory): add integration tests covering AC-1 through AC-4 + full memory loop"
```

---

## Self-Review Checklist

### Spec coverage

| Requirement | Task |
|---|---|
| AC-1: fact in `learned_facts` with embedding | Task 5 (unit) + Task 8 integration |
| AC-2: conflict → `awaiting_conflict_clarification=True` + notification | Task 5 (unit) + Task 8 integration |
| AC-3: unrelated query resets `awaiting_correction` | Task 3 (unit) + Task 8 integration |
| AC-4: correction → `model_corrections` with embedding | Task 6 (unit) + Task 8 integration |
| MemoryRetrievalNode dual-table parallel search | Task 1 |
| Memory Agent Case 1 (fact extraction) | Task 2 |
| Memory Agent Case 2 (correction detection) | Task 3 |
| Memory Agent Case 3 (conflict clarification) | Task 4 |
| Conflict message format (⚠️) appended to final_answer | Task 5 |
| User-resolved conflict skips re-check and writes directly | Tasks 4 + 5 |
| Graph wiring: `redact_outbound → memory_agent → memory_persistence` | Task 7 |
| Embedding via Ollama `qwen3-embedding:0.6b` (dim=1024) | Task 1 (utility) |
| Correction embedding encodes `correction` field, not `original_answer` | Task 6 |
| `conflicts_with` populated by persistence, carried into next turn | Tasks 4 + 5 |

### Placeholder scan

No TBDs, TODOs, or "similar to" references. All code blocks are complete. The only intentional placeholder was `_persist_correction`'s `pass` in Task 5, which is explicitly called out and filled in Task 6.

### Type consistency

| Symbol | Defined in | Used in Tasks |
|---|---|---|
| `MemoryItem` | `graphs/state.py` (Ticket 4) | 1 |
| `FactUpdate` | `graphs/state.py` (Ticket 4) | 2, 3, 4, 5, 6, 8 |
| `CorrectionUpdate` | `graphs/state.py` (Ticket 4) | 3, 6, 8 |
| `SecondBrainState` | `graphs/state.py` (Ticket 4) | all |
| `get_embedding` | `utils/embedding.py` (Task 1) | 1, 5, 6, 8 |
| `embedding_to_pg_literal` | `utils/embedding.py` (Task 1) | 1, 5 |
| `AsyncSessionLocal` | `nodes/memory_retrieval.py` (Task 1), `nodes/memory_persistence.py` (Task 5) | 1, 5 |
| `memory_agent_node` | `nodes/memory_agent.py` (Task 2) | 7, 8 |
| `memory_persistence_node` | `nodes/memory_persistence.py` (Task 5) | 7, 8 |
| `memory_retrieval_node` | `nodes/memory_retrieval.py` (Task 1) | 7, 8 |
| `LearnedFact` | `db/models.py` (Ticket 1) | 5, 8 |
| `ModelCorrection` | `db/models.py` (Ticket 1) | 6, 8 |
| `_persist_correction` | defined in Task 5, implemented in Task 6 | 5, 6 |

All names are consistent across tasks.
