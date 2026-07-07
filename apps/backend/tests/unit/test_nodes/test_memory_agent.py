from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from second_brain.graphs.state import (
  MemoryAgentOutput,
  MemoryCase,
  SecondBrainState,
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

  state = _make_state(
    messages=[HumanMessage(content="I work as a software engineer in Berlin.")]
  )

  with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
    mock_llm.ainvoke = AsyncMock(
      return_value=_output(
        MemoryCase.FACT_EXTRACTION,
        facts=[
          {
            "fact": "The user is a software engineer in Berlin.",
            "confidence": 0.95,
            "conflicts_with": [],
          }
        ],
      )
    )
    result = await memory_agent_node(state)

  assert len(result["fact_updates"]) == 1
  assert (
    result["fact_updates"][0]["fact"] == "The user is a software engineer in Berlin."
  )
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
  """Case 2: user corrects uncertain answer → correction_updates populated."""
  from second_brain.nodes.memory_agent import memory_agent_node

  state = _make_state(
    messages=[
      AIMessage(content="I think the capital of France is Lyon, but I'm not sure."),
      HumanMessage(content="Actually it's Paris, not Lyon."),
    ],
    awaiting_correction=True,
  )

  with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
    mock_llm.ainvoke = AsyncMock(
      return_value=_output(
        MemoryCase.CORRECTION,
        corrections=[
          {
            "original_answer": (
              "I think the capital of France is Lyon, but I'm not sure."
            ),
            "correction": "The capital of France is Paris.",
            "root_cause": "AI confused Lyon with Paris.",
          }
        ],
      )
    )
    result = await memory_agent_node(state)

  assert result["awaiting_correction"] is False
  assert len(result["correction_updates"]) == 1
  assert (
    result["correction_updates"][0]["correction"] == "The capital of France is Paris."
  )


@pytest.mark.asyncio
async def test_case2_unrelated_query_resets_awaiting_correction():
  """AC-3: unrelated query with awaiting_correction=True resets flag."""
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
  """Case 3: user clarifies conflict → both awaiting flags reset to False."""
  from second_brain.nodes.memory_agent import memory_agent_node

  state = _make_state(
    messages=[HumanMessage(content="Use the new one — I moved to Tokyo.")],
    awaiting_conflict_clarification=True,
    awaiting_correction=False,
    conflict_context=[
      {
        "existing": "User lives in Berlin",
        "existing_id": "id-1",
        "new": "User lives in Tokyo",
      }
    ],
    fact_updates=[
      {
        "fact": "User lives in Tokyo",
        "confidence": 0.9,
        "conflicts_with": ["id-1"],
      }
    ],
  )

  with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
    mock_llm.ainvoke = AsyncMock(
      return_value=_output(
        MemoryCase.CONFLICT_RESOLUTION,
        facts=[
          {
            "fact": "User lives in Tokyo",
            "confidence": 0.95,
            "conflicts_with": [],
          }
        ],
      )
    )
    result = await memory_agent_node(state)

  assert result["awaiting_conflict_clarification"] is False
  assert result["awaiting_correction"] is False  # D4: mutually exclusive
  assert result["conflict_context"] == []
  assert len(result["fact_updates"]) == 1
  # F1 fix: conflicts_with must be annotated from pending_facts (LLM may omit UUID)
  assert result["fact_updates"][0]["conflicts_with"] == ["id-1"]


@pytest.mark.asyncio
async def test_case3_keep_existing_returns_empty_fact_updates():
  """Case 3: keep_existing → empty fact_updates (nothing to write)."""
  from second_brain.nodes.memory_agent import memory_agent_node

  state = _make_state(
    messages=[HumanMessage(content="Keep the old one.")],
    awaiting_conflict_clarification=True,
    conflict_context=[
      {
        "existing": "User lives in Berlin",
        "existing_id": "id-1",
        "new": "User lives in Tokyo",
      }
    ],
    fact_updates=[
      {
        "fact": "User lives in Tokyo",
        "confidence": 0.9,
        "conflicts_with": ["id-1"],
      }
    ],
  )

  with patch("second_brain.nodes.memory_agent._llm") as mock_llm:
    mock_llm.ainvoke = AsyncMock(return_value=_output(MemoryCase.CONFLICT_RESOLUTION))
    result = await memory_agent_node(state)

  assert result["awaiting_conflict_clarification"] is False
  assert result["fact_updates"] == []
