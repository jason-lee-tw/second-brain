from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
  from second_brain.db.models import LearnedFact
  from second_brain.nodes.memory_persistence import memory_persistence_node

  state = _make_state(
    fact_updates=[
      {
        "fact": "The user is a vegetarian.",
        "confidence": 0.9,
        "conflicts_with": [],
      }
    ],
  )

  with (
    patch(
      "second_brain.nodes.memory_persistence.embed_text",
      new_callable=AsyncMock,
      return_value=[0.5] * 1024,
    ),
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool(),
    ),
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
    fact_updates=[
      {
        "fact": "User lives in Tokyo",
        "confidence": 0.95,
        "conflicts_with": ["00000000-0000-0000-0000-000000000001"],
      }
    ],
  )
  mock_pool = _mock_pool()

  with (
    patch(
      "second_brain.nodes.memory_persistence.embed_text",
      new_callable=AsyncMock,
      return_value=[0.3] * 1024,
    ),
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=mock_pool,
    ),
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
  """AC-2: conflicting fact → awaiting_conflict_clarification=True, NOT written."""
  from second_brain.nodes.memory_persistence import memory_persistence_node

  conflict_row = {"id": "existing-id", "fact": "User lives in Berlin", "score": 0.92}
  state = _make_state(
    final_answer="You mentioned moving.",
    fact_updates=[
      {
        "fact": "User lives in Tokyo",
        "confidence": 0.9,
        "conflicts_with": [],
      }
    ],
  )

  with (
    patch(
      "second_brain.nodes.memory_persistence.embed_text",
      new_callable=AsyncMock,
      return_value=[0.5] * 1024,
    ),
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool([conflict_row]),
    ),
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
  """AC-4: correction_update → ModelCorrection; embed_text called with correction."""
  from second_brain.db.models import ModelCorrection
  from second_brain.nodes.memory_persistence import memory_persistence_node

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

  with (
    patch(
      "second_brain.nodes.memory_persistence.embed_text",
      new_callable=AsyncMock,
      return_value=[0.3] * 1024,
    ) as mock_embed,
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
    fact_updates=[
      {
        "fact": "User is a developer.",
        "confidence": 0.9,
        "conflicts_with": [],
      }
    ],
  )

  with (
    patch(
      "second_brain.nodes.memory_persistence.embed_text",
      new_callable=AsyncMock,
      return_value=[0.1] * 1024,
    ),
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool(),
    ),
    patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
  ):
    mock_session = MagicMock()
    mock_session.commit.side_effect = RuntimeError("DB write failed")
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    with pytest.raises(RuntimeError, match="DB write failed"):
      await memory_persistence_node(state)


# ── awaiting_correction set by memory_persistence ─────────────────────────────


@pytest.mark.asyncio
async def test_sets_awaiting_correction_true_when_is_uncertain():
  """D9: is_uncertain=True → awaiting_correction=True in persistence output."""
  from second_brain.nodes.memory_persistence import memory_persistence_node

  state = _make_state(is_uncertain=True)

  with (
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool(),
    ),
    patch("second_brain.nodes.memory_persistence.Session"),
  ):
    result = await memory_persistence_node(state)

  assert result["awaiting_correction"] is True


@pytest.mark.asyncio
async def test_sets_awaiting_correction_false_when_not_uncertain():
  """confident turn → awaiting_correction=False in persistence output."""
  from second_brain.nodes.memory_persistence import memory_persistence_node

  state = _make_state(is_uncertain=False)

  with (
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool(),
    ),
    patch("second_brain.nodes.memory_persistence.Session"),
  ):
    result = await memory_persistence_node(state)

  assert result["awaiting_correction"] is False


# ── F1 regression: conflict loop ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_f1_no_conflict_loop_when_awaiting_clarification():
  """F1: when awaiting_conflict_clarification=True and LLM omits conflicts_with UUID,
  persistence must NOT re-enter conflict state (infinite loop prevention).

  Root cause: _persist_fact re-runs _conflict_check when conflicts_with=[] even
  during conflict-resolution turns, triggering another awaiting_conflict cycle.
  """
  from second_brain.nodes.memory_persistence import memory_persistence_node

  # Simulate: conflict was already detected last turn; LLM failed to propagate UUID
  conflict_row = {"id": "existing-id", "fact": "User lives in Berlin", "score": 0.92}
  state = _make_state(
    awaiting_conflict_clarification=True,
    fact_updates=[
      {
        "fact": "User lives in Tokyo",
        "confidence": 0.9,
        "conflicts_with": [],  # LLM omitted UUID — the F1 bug trigger
      }
    ],
  )

  with (
    patch(
      "second_brain.nodes.memory_persistence.embed_text",
      new_callable=AsyncMock,
      return_value=[0.5] * 1024,
    ),
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool([conflict_row]),
    ),
    patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
  ):
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    result = await memory_persistence_node(state)

  # Must NOT re-enter conflict state — that would restart the loop
  assert result["awaiting_conflict_clarification"] is False
  # Fact must be written (user already resolved conflict by choosing the new one)
  mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_f1_keep_existing_produces_no_write_and_no_conflict():
  """F1 edge: if user resolved by keeping old fact (fact_updates=[]),
  persistence must write nothing and set awaiting_conflict_clarification=False.
  """
  from second_brain.nodes.memory_persistence import memory_persistence_node

  state = _make_state(
    awaiting_conflict_clarification=True,
    fact_updates=[],  # memory_agent returned empty (keep existing)
  )

  with (
    patch(
      "second_brain.nodes.memory_persistence.get_pgvector_pool",
      new_callable=AsyncMock,
      return_value=_mock_pool(),
    ),
    patch("second_brain.nodes.memory_persistence.Session") as mock_session_cls,
  ):
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    result = await memory_persistence_node(state)

  assert result["awaiting_conflict_clarification"] is False
  mock_session.add.assert_not_called()
