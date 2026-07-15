"""OTEL tracing setup and LangGraph node span decorator."""

import functools
import inspect
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from phoenix.otel import register

from second_brain.db.session import engine


def setup_tracing(
  phoenix_collection_endpoint: str,
) -> TracerProvider:
  """Configure the global OTEL TracerProvider with Phoenix as the trace backend.

  Call once at app startup (inside the FastAPI lifespan).

  Args:
      phoenix_collection_endpoint: OTLP/gRPC collector URL, e.g.
          ``http://host.docker.internal:4317``.
          arize-phoenix-otel register() accepts http:// for plaintext gRPC —
          not HTTPS, not grpc://.
          The backend reaches Phoenix via the Docker host port — the two
          services are on isolated networks by design.

  Returns:
      The configured ``TracerProvider``, also set as the global provider via
      ``opentelemetry.trace.set_tracer_provider()``.
  """
  provider = register(
    project_name="second-brain",
    endpoint=phoenix_collection_endpoint,
    # auto_instrument=True causes register() to auto-discover and activate all
    # installed openinference-instrumentation-* packages; no separate
    # LangChainInstrumentor().instrument() call needed. It does NOT cover raw
    # driver calls (httpx, asyncpg, SQLAlchemy, psycopg) — those need their own
    # instrumentor, wired up explicitly below.
    auto_instrument=True,
  )
  HTTPXClientInstrumentor().instrument()
  AsyncPGInstrumentor().instrument()
  # engine= is required: a bare instrument() call only patches the create_engine()
  # factory and Engine.connect() at the class level. It never attaches an
  # EngineTracer to an engine that already exists — and db/session.py constructs
  # `engine` as a module-level singleton at import time, before setup_tracing()
  # runs in the FastAPI lifespan — so write spans would never appear otherwise.
  SQLAlchemyInstrumentor().instrument(engine=engine)
  PsycopgInstrumentor().instrument()
  return provider


def trace_node(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
  """Decorator that wraps an async LangGraph node function in an OTEL span.

  The span is a child of whatever span is active when the node is called,
  making it appear nested under the HTTP request span in Phoenix.

  Usage::

      @trace_node("orchestrator")
      async def orchestrator_node(state: SecondBrainState) -> SecondBrainState:
          ...

  .. note::
      Only async functions may be decorated. Applying ``@trace_node`` to a
      synchronous function raises ``TypeError`` at decoration time.

  Args:
      name: The span name displayed in the Phoenix trace waterfall.
  """

  def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
    is_async = inspect.iscoroutinefunction(func) or inspect.iscoroutinefunction(
      getattr(func, "__call__", None)
    )
    if not is_async:
      raise TypeError(f"trace_node can only decorate async functions, got: {func!r}")
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
