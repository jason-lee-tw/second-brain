"""Unit tests for the observability/tracing module.

Tests cover:
- setup_tracing() wires the Phoenix OTEL exporter correctly
- trace_node() decorator creates a named span and preserves return values
"""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from second_brain.observability.tracing import setup_tracing, trace_node


@pytest.fixture
def in_memory_tracer():
    """Replace the global OTEL TracerProvider with an in-memory one per test."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    original_provider = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)
    yield exporter
    # NOTE: set_tracer_provider here is a no-op due to the OTel Once guard.
    # Actual provider restoration is handled by the autouse fixture in conftest.py.
    # Do not remove conftest.py thinking this teardown already covers it.
    trace.set_tracer_provider(original_provider)
    exporter.clear()


class TestSetupTracing:
    def test_calls_register_with_endpoint_and_default_service_name(self):
        """setup_tracing() delegates to phoenix.otel.register with the endpoint."""
        mock_provider = MagicMock(spec=TracerProvider)
        with patch(
            "second_brain.observability.tracing.register",
            return_value=mock_provider,
        ) as mock_register:
            result = setup_tracing(phoenix_collection_endpoint="http://localhost:4317")

        mock_register.assert_called_once_with(
            project_name="second-brain",
            endpoint="http://localhost:4317",
        )
        assert result is mock_provider

    def test_accepts_custom_service_name(self):
        """setup_tracing() passes a custom service_name to register as project_name."""
        mock_provider = MagicMock(spec=TracerProvider)
        with patch(
            "second_brain.observability.tracing.register",
            return_value=mock_provider,
        ) as mock_register:
            setup_tracing(
                phoenix_collection_endpoint="http://localhost:4317",
                service_name="my-service",
            )

        mock_register.assert_called_once_with(
            project_name="my-service",
            endpoint="http://localhost:4317",
        )


class TestTraceNode:
    @pytest.mark.asyncio
    async def test_creates_span_with_correct_name(self, in_memory_tracer):
        """trace_node decorator creates a span whose name matches the argument."""

        @trace_node("my-agent-node")
        async def dummy_node(state: dict) -> dict:
            return state

        await dummy_node({"x": 1})

        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my-agent-node"

    @pytest.mark.asyncio
    async def test_preserves_function_return_value(self, in_memory_tracer):
        """trace_node does not alter the wrapped function's return value."""

        @trace_node("noop-node")
        async def dummy_node(state: dict) -> dict:
            return {"result": "done", "count": 42}

        result = await dummy_node({})

        assert result == {"result": "done", "count": 42}

    @pytest.mark.asyncio
    async def test_preserves_original_function_name(self):
        """trace_node uses functools.wraps so __name__ is not clobbered."""
        # no in_memory_tracer fixture — testing functools.wraps __name__ only

        @trace_node("whatever")
        async def my_special_node(state: dict) -> dict:
            return state

        assert my_special_node.__name__ == "my_special_node"

    @pytest.mark.asyncio
    async def test_exception_propagates_through_span(self, in_memory_tracer):
        """
        Exceptions propagate out; span is closed with ERROR status and exception
        event recorded.
        """

        @trace_node("error-node")
        async def failing_node(state: dict) -> dict:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await failing_node({})

        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].end_time is not None
        assert spans[0].status.status_code == StatusCode.ERROR
        assert any(e.name == "exception" for e in spans[0].events)

    def test_raises_type_error_for_sync_function(self):
        """
        trace_node raises TypeError at decoration time if applied to a sync function.
        """
        with pytest.raises(TypeError, match="async functions"):

            @trace_node("sync-node")
            def sync_node(state: dict) -> dict:
                return state

    @pytest.mark.asyncio
    async def test_tracer_obtained_before_provider_set_still_records_spans(self):
        """@trace_node decorators applied at import time (before setup_tracing)
        still produce spans because ProxyTracer lazily forwards to the real provider.

        This exercises the production import-order: LangGraph nodes are decorated
        at module level, before the FastAPI lifespan calls setup_tracing().
        """
        # Decorate BEFORE setting the in-memory provider — simulates import-time
        # decoration
        @trace_node("pre-setup-node")
        async def node(state: dict) -> dict:
            return state

        # NOW wire up the in-memory provider (as setup_tracing() does in the lifespan)
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        # _reset_otel_tracer_provider autouse (conftest.py) restores
        # OTel global state on teardown — no explicit cleanup needed here.
        trace.set_tracer_provider(provider)

        await node({})

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "pre-setup-node"


class TestFastAPIInstrumentation:
    def test_main_app_health_emits_span(self):
        """The real main.py app produces spans for /health when tracing is active.

        setup_tracing() is mocked so no connection to Phoenix is attempted.
        FastAPIInstrumentor.instrument_app() is called at import time in main.py,
        so the middleware is present whenever main.py is imported.
        """
        from fastapi.testclient import TestClient

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        original_provider = trace.get_tracer_provider()
        trace.set_tracer_provider(provider)

        try:
            # Patch setup_tracing so the lifespan does not override our test provider.
            with patch("second_brain.main.setup_tracing"):
                from second_brain.main import app

                # Context manager triggers lifespan (patched setup_tracing).
                with TestClient(app) as client:
                    response = client.get("/health")

            assert response.status_code == 200
            spans = exporter.get_finished_spans()
            assert len(spans) >= 1
            assert any("GET /health" in s.name for s in spans)
        finally:
            trace.set_tracer_provider(original_provider)
            exporter.clear()


class TestMainLifespan:
    def test_lifespan_shuts_down_tracer_provider_on_exit(self):
        """Lifespan teardown calls provider.shutdown() to flush buffered spans."""
        from unittest.mock import MagicMock, patch

        from fastapi.testclient import TestClient
        from opentelemetry.sdk.trace import TracerProvider

        mock_provider = MagicMock(spec=TracerProvider)

        with patch("second_brain.main.setup_tracing", return_value=mock_provider):
            from second_brain.main import app

            with TestClient(app):
                pass  # lifespan enters and exits

        mock_provider.shutdown.assert_called_once()

    def test_lifespan_logs_warning_when_shutdown_raises(self, caplog):
        """Lifespan teardown catches shutdown errors and logs a warning."""
        import logging
        from unittest.mock import MagicMock, patch

        from fastapi.testclient import TestClient
        from opentelemetry.sdk.trace import TracerProvider

        mock_provider = MagicMock(spec=TracerProvider)
        mock_provider.shutdown.side_effect = RuntimeError("flush timeout")

        with patch("second_brain.main.setup_tracing", return_value=mock_provider):
            from second_brain.main import app
            with caplog.at_level(logging.WARNING, logger="second_brain.main"):
                with TestClient(app):
                    pass  # lifespan enters and exits

        mock_provider.shutdown.assert_called_once()
        assert "TracerProvider shutdown raised an exception" in caplog.text
