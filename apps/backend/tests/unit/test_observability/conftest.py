"""conftest for test_observability.

The OpenTelemetry SDK protects the global TracerProvider with a `Once` guard
that silently ignores any call to `set_tracer_provider()` after the first one.
This breaks fixtures that need to swap the provider per-test.

This autouse fixture saves and restores the internal OTel state around every
test, so each test gets a clean provider slot.
"""

import opentelemetry.trace as trace_api
import pytest


@pytest.fixture(autouse=True)
def _reset_otel_tracer_provider():
    """Save and restore the OTel global TracerProvider state around each test."""
    # Accesses OTel private internals to reset global state between tests.
    # Verified against opentelemetry-api >=1.29. If this fails, the OTel internal
    # API has changed — update this fixture accordingly.
    assert hasattr(trace_api, "_TRACER_PROVIDER_SET_ONCE"), (
        "OTel internal API changed — update _reset_otel_tracer_provider in conftest.py"
    )
    original_provider = trace_api._TRACER_PROVIDER
    original_done = trace_api._TRACER_PROVIDER_SET_ONCE._done
    yield
    trace_api._TRACER_PROVIDER = original_provider
    trace_api._TRACER_PROVIDER_SET_ONCE._done = original_done
