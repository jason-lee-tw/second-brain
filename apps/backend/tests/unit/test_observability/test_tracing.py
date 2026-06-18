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
            result = setup_tracing(phoenix_endpoint="http://localhost:6006/v1/traces")

        mock_register.assert_called_once_with(
            project_name="second-brain",
            endpoint="http://localhost:6006/v1/traces",
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
                phoenix_endpoint="http://localhost:6006/v1/traces",
                service_name="my-service",
            )

        mock_register.assert_called_once_with(
            project_name="my-service",
            endpoint="http://localhost:6006/v1/traces",
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
    async def test_span_is_finished_after_return(self, in_memory_tracer):
        """The span created by trace_node is closed before the decorator returns."""
        @trace_node("finishing-node")
        async def dummy_node(state: dict) -> dict:
            return state

        await dummy_node({})

        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].end_time is not None

    @pytest.mark.asyncio
    async def test_preserves_original_function_name(self):
        """trace_node uses functools.wraps so __name__ is not clobbered."""
        @trace_node("whatever")
        async def my_special_node(state: dict) -> dict:
            return state

        assert my_special_node.__name__ == "my_special_node"

    @pytest.mark.asyncio
    async def test_exception_propagates_through_span(self, in_memory_tracer):
        """Exceptions raised inside the node propagate out; span is still closed."""
        @trace_node("error-node")
        async def failing_node(state: dict) -> dict:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await failing_node({})

        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].end_time is not None
