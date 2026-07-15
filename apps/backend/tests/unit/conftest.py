"""Shared test fixtures and factories for unit tests."""

import opentelemetry.trace as trace_api
import pytest
from langchain_core.messages import HumanMessage

from second_brain.graphs.state import SecondBrainState


@pytest.fixture(autouse=True)
def _reset_otel_tracer_provider():
  """Saves/restores _TRACER_PROVIDER and _TRACER_PROVIDER_SET_ONCE._done.

  The OpenTelemetry SDK protects the global TracerProvider with a `Once` guard
  that silently ignores any call to `set_tracer_provider()` after the first
  one. Several test modules (e.g. test_graphs/test_ingestion_graph.py,
  test_graphs/test_query_graph_build.py, test_observability/test_tracing.py)
  swap in an in-memory provider to assert span emission; without a reset,
  that swap permanently trips the Once guard for the rest of the pytest
  session and breaks every other test that also needs to swap providers
  per-test.

  Defined here (parent conftest) so it applies to all subdirectories via
  pytest's fixture discovery, rather than being duplicated per directory.
  """
  # Accesses OTel private internals to reset global state between tests.
  # Verified against opentelemetry-api >=1.29. If this fails, the OTel internal
  # API has changed — update this fixture accordingly.
  assert hasattr(trace_api, "_TRACER_PROVIDER_SET_ONCE") and hasattr(
    trace_api, "_TRACER_PROVIDER"
  ), (
    "OTel internal API changed (verified against opentelemetry-api>=1.29) "
    "— update _reset_otel_tracer_provider in conftest.py"
  )
  original_provider = trace_api._TRACER_PROVIDER
  original_done = trace_api._TRACER_PROVIDER_SET_ONCE._done
  yield
  trace_api._TRACER_PROVIDER = original_provider
  trace_api._TRACER_PROVIDER_SET_ONCE._done = original_done


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
