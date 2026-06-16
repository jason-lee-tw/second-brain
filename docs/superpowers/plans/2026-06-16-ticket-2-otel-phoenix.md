# OpenTelemetry + Arize Phoenix Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument the FastAPI app with OpenTelemetry and export traces to Arize Phoenix so that a single `GET /health` request produces a visible end-to-end trace in the Phoenix UI at `http://localhost:6006`.

**Architecture:** A `setup_tracing()` function initialises the global OTEL `TracerProvider` once at app startup (inside the FastAPI lifespan). `FastAPIInstrumentor.instrument_app(app)` wraps the app at module level so every HTTP request automatically gets a root span. A `trace_node(name)` decorator is defined for future use wrapping async LangGraph node functions with child spans.

**Tech Stack:** `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-fastapi`, `arize-phoenix-otel`, `pytest-asyncio`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `apps/backend/pyproject.toml` | Add OTEL + Phoenix packages to dependencies |
| Modify | `apps/backend/src/second_brain/config.py` | Add `phoenix_endpoint` field to `Settings` |
| Modify | `apps/backend/.env.template` | Document `PHOENIX_ENDPOINT` variable |
| Create | `apps/backend/src/second_brain/observability/__init__.py` | Package marker, re-exports public API |
| Create | `apps/backend/src/second_brain/observability/tracing.py` | `setup_tracing()` + `trace_node` decorator |
| Create | `apps/backend/tests/unit/test_observability/__init__.py` | Test package marker |
| Create | `apps/backend/tests/unit/test_observability/test_tracing.py` | All observability unit tests |
| Modify | `apps/backend/src/second_brain/main.py` | Call `setup_tracing()` in lifespan; add FastAPI instrumentation |
| Modify | `docker-compose.yml` | Add `extra_hosts` to backend service for Linux host-port access |

---

### Task 1: Add OTEL and Phoenix packages to pyproject.toml

**Files:**
- Modify: `apps/backend/pyproject.toml`

- [ ] **Step 1: Add OTEL dependencies**

  Open `apps/backend/pyproject.toml`. Add the following packages to the `[project] dependencies` list. The rest of the file (existing deps, build config, pytest config) stays unchanged.

  ```toml
  [project]
  name = "second-brain"
  version = "0.1.0"
  requires-python = ">=3.12"
  dependencies = [
      "fastapi[standard]>=0.115",
      "pydantic-settings>=2.7",
      "sqlmodel>=0.0.22",
      "alembic>=1.14",
      "asyncpg>=0.30",
      "pgvector>=0.3",
      # --- Ticket 2: observability ---
      "opentelemetry-sdk>=1.29",
      "opentelemetry-exporter-otlp-proto-http>=1.29",
      "opentelemetry-instrumentation-fastapi>=0.50b0",
      "arize-phoenix-otel>=0.8",
  ]

  [project.optional-dependencies]
  dev = [
      "pytest>=8.3",
      "pytest-asyncio>=0.24",
      "httpx>=0.27",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/second_brain"]

  [tool.pytest.ini_options]
  testpaths = ["tests"]
  ```

- [ ] **Step 2: Install packages**

  ```bash
  cd apps/backend && uv sync
  ```

  Expected: All packages installed, no errors. Verify with:
  ```bash
  cd apps/backend && python -c "import opentelemetry; import phoenix.otel; print('OK')"
  ```
  Expected output: `OK`

- [ ] **Step 3: Commit**

  ```bash
  git add apps/backend/pyproject.toml
  git commit -m "chore: add OTEL and arize-phoenix-otel packages"
  ```

---

### Task 2: Extend Settings with phoenix_endpoint

**Files:**
- Modify: `apps/backend/src/second_brain/config.py`
- Modify: `apps/backend/.env.template`

- [ ] **Step 1: Add `phoenix_endpoint` to `Settings`**

  Replace the full contents of `apps/backend/src/second_brain/config.py`:

  ```python
  from pydantic_settings import BaseSettings, SettingsConfigDict


  class Settings(BaseSettings):
      database_url: str
      ollama_base_url: str = "http://localhost:11434"
      anthropic_api_key: str
      tavily_api_key: str
      # OTEL collector endpoint — backend reaches Phoenix via host port 6006.
      # On Linux Docker hosts, 'host.docker.internal' resolves via extra_hosts.
      phoenix_endpoint: str = "http://host.docker.internal:6006/v1/traces"

      model_config = SettingsConfigDict(env_file=".env")


  settings = Settings()
  ```

- [ ] **Step 2: Update `.env.template`**

  Replace the full contents of `apps/backend/.env.template`:

  ```dotenv
  DATABASE_URL="postgresql+asyncpg://second_brain:secret@localhost:5432/second_brain"
  OLLAMA_BASE_URL="http://localhost:11434"
  ANTHROPIC_API_KEY="your-anthropic-api-key-here"
  TAVILY_API_KEY="your-tavily-api-key-here"
  # Arize Phoenix OTEL collector. Override on Linux if host.docker.internal doesn't resolve.
  PHOENIX_ENDPOINT="http://host.docker.internal:6006/v1/traces"
  ```

- [ ] **Step 3: Verify settings load**

  ```bash
  cd apps/backend && python -c "
  from second_brain.config import Settings
  s = Settings(
      database_url='postgresql+asyncpg://x:x@localhost/x',
      anthropic_api_key='test',
      tavily_api_key='test',
  )
  print(s.phoenix_endpoint)
  "
  ```

  Expected output: `http://host.docker.internal:6006/v1/traces`

- [ ] **Step 4: Commit**

  ```bash
  git add apps/backend/src/second_brain/config.py apps/backend/.env.template
  git commit -m "feat: add phoenix_endpoint to Settings"
  ```

---

### Task 3: Create observability/tracing.py (TDD)

**Files:**
- Create: `apps/backend/src/second_brain/observability/__init__.py`
- Create: `apps/backend/src/second_brain/observability/tracing.py`
- Create: `apps/backend/tests/unit/test_observability/__init__.py`
- Create: `apps/backend/tests/unit/test_observability/test_tracing.py`

- [ ] **Step 1: Create directories**

  ```bash
  mkdir -p apps/backend/src/second_brain/observability
  mkdir -p apps/backend/tests/unit/test_observability
  ```

- [ ] **Step 2: Write failing tests**

  Create `apps/backend/tests/unit/test_observability/__init__.py` (empty file):

  ```python
  ```

  Create `apps/backend/tests/unit/test_observability/test_tracing.py`:

  ```python
  """Unit tests for the observability/tracing module.

  Tests cover:
  - setup_tracing() wires the Phoenix OTEL exporter correctly
  - trace_node() decorator creates a named span and preserves return values
  - FastAPIInstrumentor produces HTTP-level spans (validates the pattern used in main.py)
  """
  import pytest
  from unittest.mock import MagicMock, patch

  from opentelemetry import trace
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

  from second_brain.observability.tracing import setup_tracing, trace_node


  @pytest.fixture
  def in_memory_tracer():
      """Replace the global OTEL TracerProvider with an in-memory one for the duration of a test."""
      exporter = InMemorySpanExporter()
      provider = TracerProvider()
      provider.add_span_processor(SimpleSpanProcessor(exporter))
      original_provider = trace.get_tracer_provider()
      trace.set_tracer_provider(provider)
      yield exporter
      trace.set_tracer_provider(original_provider)
      exporter.clear()


  class TestSetupTracing:
      def test_calls_register_with_endpoint_and_default_service_name(self):
          """setup_tracing() delegates to phoenix.otel.register with the given endpoint."""
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
      async def test_preserves_original_function_name(self, in_memory_tracer):
          """trace_node uses functools.wraps so __name__ is not clobbered."""
          @trace_node("whatever")
          async def my_special_node(state: dict) -> dict:
              return state

          assert my_special_node.__name__ == "my_special_node"
  ```

- [ ] **Step 3: Run tests — verify they fail**

  ```bash
  cd apps/backend && pytest tests/unit/test_observability/test_tracing.py -v
  ```

  Expected: **FAIL** — collection error:
  ```
  ModuleNotFoundError: No module named 'second_brain.observability'
  ```

- [ ] **Step 4: Create the observability package marker**

  Create `apps/backend/src/second_brain/observability/__init__.py`:

  ```python
  """Observability utilities — OTEL setup and LangGraph node tracing."""

  from second_brain.observability.tracing import setup_tracing, trace_node

  __all__ = ["setup_tracing", "trace_node"]
  ```

- [ ] **Step 5: Run tests again — verify updated failure**

  ```bash
  cd apps/backend && pytest tests/unit/test_observability/test_tracing.py -v
  ```

  Expected: **FAIL** — collection error:
  ```
  ModuleNotFoundError: No module named 'second_brain.observability.tracing'
  ```

- [ ] **Step 6: Implement `tracing.py`**

  Create `apps/backend/src/second_brain/observability/tracing.py`:

  ```python
  """OTEL tracing setup and LangGraph node span decorator."""

  import functools
  from typing import Any, Callable

  from opentelemetry import trace
  from opentelemetry.sdk.trace import TracerProvider
  from phoenix.otel import register


  def setup_tracing(
      phoenix_endpoint: str,
      service_name: str = "second-brain",
  ) -> TracerProvider:
      """Configure the global OTEL TracerProvider with Phoenix as the trace backend.

      Call once at app startup (inside the FastAPI lifespan).

      Args:
          phoenix_endpoint: OTLP HTTP collector URL, e.g.
              ``http://host.docker.internal:6006/v1/traces``.
              The backend reaches Phoenix via the Docker host port — the two
              services are on isolated networks by design.
          service_name: The service name shown in the Phoenix UI.

      Returns:
          The configured ``TracerProvider``, also set as the global provider via
          ``opentelemetry.trace.set_tracer_provider()``.
      """
      provider: TracerProvider = register(
          project_name=service_name,
          endpoint=phoenix_endpoint,
      )
      return provider


  def trace_node(name: str) -> Callable:
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
      def decorator(func: Callable) -> Callable:
          @functools.wraps(func)
          async def wrapper(*args: Any, **kwargs: Any) -> Any:
              tracer = trace.get_tracer(__name__)
              with tracer.start_as_current_span(name):
                  return await func(*args, **kwargs)
          return wrapper
      return decorator
  ```

- [ ] **Step 7: Run tests — verify they pass**

  ```bash
  cd apps/backend && pytest tests/unit/test_observability/test_tracing.py -v
  ```

  Expected: **PASS** — all 6 tests pass:
  ```
  tests/unit/test_observability/test_tracing.py::TestSetupTracing::test_calls_register_with_endpoint_and_default_service_name PASSED
  tests/unit/test_observability/test_tracing.py::TestSetupTracing::test_accepts_custom_service_name PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_creates_span_with_correct_name PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_preserves_function_return_value PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_span_is_finished_after_return PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_preserves_original_function_name PASSED
  6 passed in ...
  ```

- [ ] **Step 8: Commit**

  ```bash
  git add \
    apps/backend/src/second_brain/observability/__init__.py \
    apps/backend/src/second_brain/observability/tracing.py \
    apps/backend/tests/unit/test_observability/__init__.py \
    apps/backend/tests/unit/test_observability/test_tracing.py
  git commit -m "feat: add observability/tracing.py with setup_tracing and trace_node"
  ```

---

### Task 4: Wire tracing into main.py with FastAPI auto-instrumentation (TDD)

**Files:**
- Modify: `apps/backend/src/second_brain/main.py`
- Modify: `apps/backend/tests/unit/test_observability/test_tracing.py`

- [ ] **Step 1: Write failing test — add FastAPI instrumentation test to `test_tracing.py`**

  Append the following class to the **end** of `apps/backend/tests/unit/test_observability/test_tracing.py` (after `TestTraceNode`):

  ```python
  class TestFastAPIInstrumentation:
      def test_http_request_emits_span(self):
          """FastAPIInstrumentor.instrument_app() produces a span for each HTTP request.

          This test validates the pattern applied in main.py: instrumenting a FastAPI
          app causes every request to generate an OTEL span visible in Phoenix.
          """
          from fastapi import FastAPI
          from fastapi.testclient import TestClient
          from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

          exporter = InMemorySpanExporter()
          provider = TracerProvider()
          provider.add_span_processor(SimpleSpanProcessor(exporter))
          original_provider = trace.get_tracer_provider()
          trace.set_tracer_provider(provider)

          try:
              test_app = FastAPI()

              @test_app.get("/health")
              async def health():
                  return {"status": "ok"}

              FastAPIInstrumentor.instrument_app(test_app)

              # TestClient without context manager skips lifespan — no real Phoenix needed.
              client = TestClient(test_app)
              response = client.get("/health")

              assert response.status_code == 200
              spans = exporter.get_finished_spans()
              assert len(spans) >= 1
              assert any("GET /health" in s.name for s in spans)
          finally:
              # Do NOT call FastAPIInstrumentor().uninstrument() here — that would
              # globally strip middleware from all instrumented apps (including main.app),
              # breaking test_main_app_health_emits_span which runs in the same session.
              # test_app is a local variable and gets garbage-collected safely.
              trace.set_tracer_provider(original_provider)
              exporter.clear()

      def test_main_app_health_emits_span(self):
          """The real main.py app produces spans for /health when tracing is active.

          setup_tracing() is mocked so no connection to Phoenix is attempted.
          FastAPIInstrumentor.instrument_app() is called at import time in main.py,
          so the middleware is present whenever main.py is imported.
          """
          from unittest.mock import patch
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
                  # Use context manager to trigger lifespan (calls the patched setup_tracing).
                  with TestClient(app) as client:
                      response = client.get("/health")

              assert response.status_code == 200
              spans = exporter.get_finished_spans()
              assert len(spans) >= 1
              assert any("GET /health" in s.name for s in spans)
          finally:
              trace.set_tracer_provider(original_provider)
              exporter.clear()
  ```

- [ ] **Step 2: Run new tests — verify they fail**

  ```bash
  cd apps/backend && pytest tests/unit/test_observability/test_tracing.py::TestFastAPIInstrumentation -v
  ```

  Expected: **FAIL**
  ```
  FAILED ...test_main_app_health_emits_span - AttributeError: <module 'second_brain.main'> does not have the attribute 'setup_tracing'
  ```

  (The first test `test_http_request_emits_span` will pass because it doesn't depend on `main.py`; the second will fail because `main.py` doesn't import `setup_tracing` yet.)

- [ ] **Step 3: Implement `main.py` changes**

  Replace the full contents of `apps/backend/src/second_brain/main.py`:

  ```python
  from contextlib import asynccontextmanager

  from fastapi import FastAPI
  from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

  from second_brain.config import settings
  from second_brain.observability.tracing import setup_tracing


  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Initialise the global OTEL TracerProvider once at startup.
      # All subsequent spans (HTTP middleware, trace_node decorators) use this provider.
      setup_tracing(phoenix_endpoint=settings.phoenix_endpoint)
      yield


  app = FastAPI(lifespan=lifespan)

  # Instrument at module level so the middleware is in place before any request arrives.
  # This adds OpenTelemetryMiddleware to the ASGI stack — every request gets a root span.
  FastAPIInstrumentor.instrument_app(app)


  @app.get("/health")
  async def health() -> dict[str, str]:
      return {"status": "ok"}
  ```

- [ ] **Step 4: Run all observability tests — verify they pass**

  ```bash
  cd apps/backend && pytest tests/unit/test_observability/test_tracing.py -v
  ```

  Expected: **PASS** — all 8 tests pass:
  ```
  tests/unit/test_observability/test_tracing.py::TestSetupTracing::test_calls_register_with_endpoint_and_default_service_name PASSED
  tests/unit/test_observability/test_tracing.py::TestSetupTracing::test_accepts_custom_service_name PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_creates_span_with_correct_name PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_preserves_function_return_value PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_span_is_finished_after_return PASSED
  tests/unit/test_observability/test_tracing.py::TestTraceNode::test_preserves_original_function_name PASSED
  tests/unit/test_observability/test_tracing.py::TestFastAPIInstrumentation::test_http_request_emits_span PASSED
  tests/unit/test_observability/test_tracing.py::TestFastAPIInstrumentation::test_main_app_health_emits_span PASSED
  8 passed in ...
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add \
    apps/backend/src/second_brain/main.py \
    apps/backend/tests/unit/test_observability/test_tracing.py
  git commit -m "feat: wire OTEL tracing into FastAPI lifespan and add FastAPI instrumentation"
  ```

---

### Task 5: Update docker-compose.yml for Linux host resolution

**Files:**
- Modify: `docker-compose.yml`

**Context:** On Linux Docker hosts, containers cannot reach the host machine via `host.docker.internal` unless it is explicitly mapped. Docker Desktop (Mac/Windows) provides this automatically. Adding `extra_hosts: ["host.docker.internal:host-gateway"]` to the backend service makes the hostname resolve on Linux without breaking Mac/Windows.

- [ ] **Step 1: Add `extra_hosts` to the backend service**

  In `docker-compose.yml`, locate the `backend` service and add `extra_hosts`. Below is the complete file reflecting the state after Ticket 1 plus the Ticket 2 addition:

  ```yaml
  services:
    ollama-checker:
      image: curlimages/curl:latest
      env_file:
        - ./apps/backend/.env
      network_mode: host
      volumes:
        - ./docker/ollama-checker.sh:/scripts/ollama-checker.sh:ro
      entrypoint: ["sh", "/scripts/ollama-checker.sh"]
      extra_hosts:
        - "host.docker.internal:host-gateway"

    app_postgres:
      image: pgvector/pgvector:pg17
      environment:
        POSTGRES_DB: second_brain
        POSTGRES_USER: second_brain
        POSTGRES_PASSWORD: secret
      networks:
        - app_network
      volumes:
        - app_postgres_data:/var/lib/postgresql/data

    phoenix:
      image: arizephoenix/phoenix:latest
      ports:
        - "6006:6006"
      networks:
        - phoenix_network
      environment:
        - PHOENIX_SQL_DATABASE_URL=postgresql://phoenix:phoenix@phoenix_postgres:5432/phoenix

    phoenix_postgres:
      image: postgres:17
      environment:
        POSTGRES_DB: phoenix
        POSTGRES_USER: phoenix
        POSTGRES_PASSWORD: phoenix
      networks:
        - phoenix_network
      volumes:
        - phoenix_postgres_data:/var/lib/postgresql/data

    backend:
      build:
        context: ./apps/backend
        dockerfile: Dockerfile
      env_file:
        - ./apps/backend/.env
      networks:
        - app_network
      ports:
        - "8000:8000"
      depends_on:
        - app_postgres
      # Required on Linux: maps host.docker.internal → the host machine's gateway IP.
      # On Docker Desktop (Mac/Windows) this mapping is provided automatically.
      extra_hosts:
        - "host.docker.internal:host-gateway"

  networks:
    app_network:
      driver: bridge
    phoenix_network:
      driver: bridge

  volumes:
    app_postgres_data:
    phoenix_postgres_data:
  ```

- [ ] **Step 2: End-to-end verification**

  Start all services:
  ```bash
  docker compose up -d
  ```

  Wait for the backend to be healthy, then send a request:
  ```bash
  curl -s http://localhost:8000/health
  ```

  Expected response:
  ```json
  {"status": "ok"}
  ```

  Open Phoenix UI in your browser: `http://localhost:6006`

  Navigate to **Projects → second-brain**. You should see a trace with:
  - A root span named `GET /health` (from `FastAPIInstrumentor`)
  - Duration and status code visible in the waterfall view

  If the trace does not appear within 10 seconds, check backend logs:
  ```bash
  docker compose logs backend --tail=50
  ```

  Look for OTEL export errors. Common causes:
  - `phoenix_endpoint` env var overridden in `.env` to a wrong value
  - Phoenix container not healthy (`docker compose ps phoenix`)
  - On Linux: `host.docker.internal` not resolving (verify `extra_hosts` was applied with `docker inspect <backend-container>`)

- [ ] **Step 3: Commit**

  ```bash
  git add docker-compose.yml
  git commit -m "chore: add extra_hosts to backend service for Linux host.docker.internal resolution"
  ```

---

## Self-Review Checklist

| Requirement | Covered by |
|-------------|-----------|
| `setup_tracing()` in `observability/tracing.py` | Task 3 Step 6 |
| `trace_node` decorator in `observability/tracing.py` | Task 3 Step 6 |
| `main.py` calls `setup_tracing()` in lifespan | Task 4 Step 3 |
| FastAPI auto-instrumentation (`FastAPIInstrumentor`) | Task 4 Step 3 |
| `config.py` `phoenix_endpoint` field | Task 2 Step 1 |
| `.env.template` `PHOENIX_ENDPOINT` entry | Task 2 Step 2 |
| `docker-compose.yml` `extra_hosts` for backend | Task 5 Step 1 |
| Test: TracerProvider is configured | Task 3 (`TestSetupTracing`) |
| Test: `trace_node` creates spans | Task 3 (`TestTraceNode`) |
| Test: FastAPI middleware registered + produces spans | Task 4 (`TestFastAPIInstrumentation`) |
| Done-when: `GET /health` visible in Phoenix UI | Task 5 Step 2 |
