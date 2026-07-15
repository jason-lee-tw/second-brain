"""conftest for test_graphs.

The OpenTelemetry SDK protects the global TracerProvider with a `Once` guard
that silently ignores any call to `set_tracer_provider()` after the first one.
test_ingestion_graph.py swaps in an in-memory provider to assert span emission;
without a reset, that swap permanently trips the Once guard for the rest of the
pytest session and breaks other test files (e.g. test_observability) that also
need to swap providers per-test.

This autouse fixture saves and restores the internal OTel state around every
test in this directory, so each test gets a clean provider slot. Mirrors the
identical fixture in tests/unit/test_observability/conftest.py.
"""

import opentelemetry.trace as trace_api
import pytest


@pytest.fixture(autouse=True)
def _reset_otel_tracer_provider():
  """Saves/restores _TRACER_PROVIDER and _TRACER_PROVIDER_SET_ONCE._done."""
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
