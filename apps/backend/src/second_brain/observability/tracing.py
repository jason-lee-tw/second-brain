"""OTEL tracing setup and LangGraph node span decorator."""

import functools
import inspect
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from phoenix.otel import register


def setup_tracing(
    phoenix_collection_endpoint: str,
    service_name: str = "second-brain",
) -> TracerProvider:
    """Configure the global OTEL TracerProvider with Phoenix as the trace backend.

    Call once at app startup (inside the FastAPI lifespan).

    Args:
        phoenix_collection_endpoint: OTLP gRPC collector URL, e.g.
            ``http://host.docker.internal:4317``.
            The backend reaches Phoenix via the Docker host port — the two
            services are on isolated networks by design.
        service_name: The service name shown in the Phoenix UI.

    Returns:
        The configured ``TracerProvider``, also set as the global provider via
        ``opentelemetry.trace.set_tracer_provider()``.
    """
    provider: TracerProvider = register(
        project_name=service_name,
        endpoint=phoenix_collection_endpoint,
    )
    return provider


def trace_node(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that wraps an async LangGraph node function in an OTEL span.

    The span is a child of whatever span is active when the node is called,
    making it appear nested under the HTTP request span in Phoenix.

    Usage::

        @trace_node("orchestrator")
        async def orchestrator_node(state: SecondBrainState) -> SecondBrainState:
            ...

    Args:
        name: The span name displayed in the Phoenix trace waterfall.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"trace_node can only decorate async functions, got: {func!r}"
            )
        # Acquired once per decoration (not per call). Before setup_tracing() runs this
        # returns a ProxyTracer that lazily forwards to the real provider — module-level
        # decorations work correctly even when applied before the lifespan starts.
        tracer = trace.get_tracer(__name__)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(name):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
