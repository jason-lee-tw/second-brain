"""Shared test fixtures and factories for unit tests."""

from langchain_core.messages import HumanMessage

from second_brain.graphs.state import SecondBrainState


def make_state(**overrides) -> SecondBrainState:
  """Factory for SecondBrainState with sensible defaults for tests."""
  defaults: SecondBrainState = {
    "session_id": "test-session-001",
    "messages": [HumanMessage(content="Hello")],
    "rag_results": [],
    "web_results": [],
    "retrieved_memory": [],
    "routing_decision": "neither",
    "final_answer": "",
    "confidence": 0.9,
    "is_uncertain": False,
    "awaiting_correction": False,
    "awaiting_conflict_clarification": False,
    "conflict_context": [],
    "fact_updates": [],
    "correction_updates": [],
    "context_used": [],
  }
  defaults.update(overrides)  # type: ignore[typeddict-item]
  return defaults
