# Fix Missing LangChain OTEL Spans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface LangChain LLM/CHAIN/TOOL spans in Arize Phoenix by adding `openinference-instrumentation-langchain` and enabling `auto_instrument=True` in `setup_tracing()`.

**Architecture:** `phoenix.otel.register(auto_instrument=True)` auto-discovers and activates all installed `openinference-instrumentation-*` packages at startup — no manual `LangChainInstrumentor().instrument()` call needed. The existing lifespan + tracing setup in `main.py` stays unchanged.

**Tech Stack:** `openinference-instrumentation-langchain`, `arize-phoenix-otel>=0.8` (already installed)

**Spec:** `docs/superpowers/specs/2026-06-25-langchain-otel-instrumentation.md`

## Global Constraints

- `uv add`, never hand-edit `uv.lock`
- Conventional Commits enforced by `.hooks/commit-msg`
- Branch: `fix/000-langchain-otel-spans`
- Run `just lint`, `just type-check`, `just test-unit` before every commit
- Python ≥ 3.12

---

## File Map

| Action | Path | Change |
|--------|------|--------|
| Modify | `apps/backend/pyproject.toml` | Add `openinference-instrumentation-langchain` dependency |
| Modify | `apps/backend/src/second_brain/observability/tracing.py` | Add `auto_instrument=True` to `register()` call |
| Modify | `apps/backend/tests/unit/test_observability/test_tracing.py` | Update `test_calls_register_with_endpoint_and_default_service_name` to assert `auto_instrument=True` |
| Modify | `docs/codebase/001-tech-stack.md` | Note LangChain instrumentation in Observability row |

---

### Task 1: Update test → red → add package + fix → green

**Files:**
- Modify: `apps/backend/tests/unit/test_observability/test_tracing.py:39-52`
- Modify: `apps/backend/pyproject.toml`
- Modify: `apps/backend/src/second_brain/observability/tracing.py`

**Interfaces:**
- Produces: `setup_tracing(phoenix_collection_endpoint)` now calls `register(..., auto_instrument=True)`

- [ ] **Step 1: Update the existing test to assert `auto_instrument=True` (makes it red)**

  In `apps/backend/tests/unit/test_observability/test_tracing.py`, update `TestSetupTracing.test_calls_register_with_endpoint_and_default_service_name`:

  ```python
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
              auto_instrument=True,
          )
          assert result is mock_provider

      def test_auto_instrument_enabled(self):
          """setup_tracing() passes auto_instrument=True so LangChain spans are emitted."""
          mock_provider = MagicMock(spec=TracerProvider)
          with patch(
              "second_brain.observability.tracing.register",
              return_value=mock_provider,
          ) as mock_register:
              setup_tracing(phoenix_collection_endpoint="http://phoenix:4317")

          _, kwargs = mock_register.call_args
          assert kwargs.get("auto_instrument") is True
  ```

- [ ] **Step 2: Run test to confirm it is red**

  ```bash
  cd /path/to/ai-learning-milestone
  just test-unit -k "test_calls_register_with_endpoint_and_default_service_name or test_auto_instrument_enabled"
  ```

  Expected: FAIL — `AssertionError: Expected call: register(project_name='second-brain', endpoint='http://localhost:4317', auto_instrument=True)` (the kwarg is absent).

- [ ] **Step 3: Add the package dependency**

  From the workspace root (`ai-learning-milestone/`):

  ```bash
  uv add openinference-instrumentation-langchain --project apps/backend
  ```

  This updates `apps/backend/pyproject.toml` and `uv.lock`. Verify the line appears:

  ```bash
  grep "openinference" apps/backend/pyproject.toml
  ```

  Expected output: `"openinference-instrumentation-langchain>=..."`

- [ ] **Step 4: Enable `auto_instrument=True` in `setup_tracing()`**

  Edit `apps/backend/src/second_brain/observability/tracing.py`, function `setup_tracing()`, change the `register()` call:

  ```python
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
      return register(
          project_name="second-brain",
          endpoint=phoenix_collection_endpoint,
          auto_instrument=True,
      )
  ```

- [ ] **Step 5: Run tests to confirm green**

  ```bash
  just test-unit
  ```

  Expected: all tests PASS including the two `TestSetupTracing` tests.

- [ ] **Step 6: Run lint and type-check**

  ```bash
  just lint && just type-check
  ```

  Expected: no errors, no warnings.

- [ ] **Step 7: Commit**

  ```bash
  git add apps/backend/pyproject.toml uv.lock \
          apps/backend/src/second_brain/observability/tracing.py \
          apps/backend/tests/unit/test_observability/test_tracing.py
  git commit -m "fix(observability): enable LangChain OTEL instrumentation via auto_instrument"
  ```

---

### Task 2: Update tech-stack doc

**Files:**
- Modify: `docs/codebase/001-tech-stack.md`

- [ ] **Step 1: Update the Observability row**

  In `docs/codebase/001-tech-stack.md`, change the Observability row from:

  ```
  | Observability        | Arize Phoenix (OTEL) — UI at `localhost:6006`                                      |
  ```

  To:

  ```
  | Observability        | Arize Phoenix (OTEL) — UI at `localhost:6006`; `openinference-instrumentation-langchain` for LangChain/LangGraph spans |
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add docs/codebase/001-tech-stack.md
  git commit -m "docs: note LangChain OTEL instrumentation in tech-stack"
  ```

---

## Verification (runtime)

After implementing both tasks:

- [ ] Boot the stack: `just up-all`
- [ ] Send a query:
  ```bash
  curl -s -X POST http://localhost:3001/query \
    -H "Content-Type: application/json" \
    -d '{"message": "what do you know?", "session_id": "test-otel"}' | jq .
  ```
- [ ] Open Phoenix at `http://localhost:6006`, navigate to project `second-brain`, find the latest trace.
- [ ] Confirm the trace contains spans with `span_kind = LLM` and `span_kind = CHAIN`.
