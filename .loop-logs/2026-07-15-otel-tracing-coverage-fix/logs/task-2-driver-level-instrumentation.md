# Task 2 Log: Add and wire up driver-level OTEL instrumentation

## Task Context

### Plan Section

## Task 2: Add and wire up driver-level OTEL instrumentation

**Files:**
- Modify: `apps/backend/pyproject.toml` (via `uv add`, not by hand)
- Modify: `apps/backend/uv.lock` (auto-updated by `uv add`)
- Modify: `apps/backend/src/second_brain/observability/tracing.py` (imports + `setup_tracing()` body)
- Test: `apps/backend/tests/unit/test_observability/test_tracing.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `setup_tracing()`'s signature and return value are unchanged; it now also globally instruments `httpx`, `asyncpg`, SQLAlchemy, and `psycopg` as a side effect of being called.

- [ ] **Step 1: Add the four dependencies**

```bash
cd apps/backend
uv add opentelemetry-instrumentation-httpx opentelemetry-instrumentation-asyncpg opentelemetry-instrumentation-sqlalchemy opentelemetry-instrumentation-psycopg
```

Verify: `git diff apps/backend/pyproject.toml apps/backend/uv.lock` shows only additive dependency entries — no version bumps or removals of existing packages.

- [ ] **Step 2: Write the failing test**

In `apps/backend/tests/unit/test_observability/test_tracing.py`, replace the existing `test_calls_register_with_correct_args` method inside `class TestSetupTracing:` with this (adds patches for the 4 new instrumentors so it stays isolated from Task's Step 4 below):

```python
  def test_calls_register_with_correct_args(self):
    """setup_tracing() calls register with endpoint and auto_instrument=True."""
    mock_provider = MagicMock(spec=TracerProvider)
    with (
      patch(
        "second_brain.observability.tracing.register",
        return_value=mock_provider,
      ) as mock_register,
      patch("second_brain.observability.tracing.HTTPXClientInstrumentor"),
      patch("second_brain.observability.tracing.AsyncPGInstrumentor"),
      patch("second_brain.observability.tracing.SQLAlchemyInstrumentor"),
      patch("second_brain.observability.tracing.PsycopgInstrumentor"),
    ):
      result = setup_tracing(phoenix_collection_endpoint="http://localhost:4317")

    mock_register.assert_called_once_with(
      project_name="second-brain",
      endpoint="http://localhost:4317",
      auto_instrument=True,
    )
    assert result is mock_provider
```

Then add a new test method directly after it, still inside `class TestSetupTracing:`:

```python
  def test_instruments_raw_drivers(self):
    """setup_tracing() must instrument httpx, asyncpg, SQLAlchemy, and psycopg —
    the raw drivers auto_instrument=True can't reach (it only activates
    openinference-instrumentation-* packages)."""
    with (
      patch("second_brain.observability.tracing.register"),
      patch("second_brain.observability.tracing.HTTPXClientInstrumentor") as mock_httpx,
      patch("second_brain.observability.tracing.AsyncPGInstrumentor") as mock_asyncpg,
      patch(
        "second_brain.observability.tracing.SQLAlchemyInstrumentor"
      ) as mock_sqlalchemy,
      patch("second_brain.observability.tracing.PsycopgInstrumentor") as mock_psycopg,
    ):
      setup_tracing(phoenix_collection_endpoint="http://localhost:4317")

    mock_httpx.return_value.instrument.assert_called_once_with()
    mock_asyncpg.return_value.instrument.assert_called_once_with()
    mock_sqlalchemy.return_value.instrument.assert_called_once_with()
    mock_psycopg.return_value.instrument.assert_called_once_with()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/test_observability/test_tracing.py::TestSetupTracing -v`
Expected: FAIL — both tests error out (`AttributeError` / import error) because `second_brain.observability.tracing` doesn't define `HTTPXClientInstrumentor`, `AsyncPGInstrumentor`, `SQLAlchemyInstrumentor`, or `PsycopgInstrumentor` yet, so `patch(...)` can't find them.

- [ ] **Step 4: Write minimal implementation**

In `apps/backend/src/second_brain/observability/tracing.py`, add these imports (alphabetical, alongside the existing `opentelemetry`/`phoenix` imports, before `from phoenix.otel import register`):

```python
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from phoenix.otel import register
```

Then change `setup_tracing()`'s body from:

```python
  return register(
    project_name="second-brain",
    endpoint=phoenix_collection_endpoint,
    # auto_instrument=True causes register() to auto-discover and activate all
    # installed openinference-instrumentation-* packages; no separate
    # LangChainInstrumentor().instrument() call needed.
    auto_instrument=True,
  )
```

to:

```python
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
  SQLAlchemyInstrumentor().instrument()
  PsycopgInstrumentor().instrument()
  return provider
```

(The docstring above `setup_tracing` is unchanged.)

- [ ] **Step 5: Run tests to verify everything passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_observability/test_tracing.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/pyproject.toml apps/backend/uv.lock apps/backend/src/second_brain/observability/tracing.py apps/backend/tests/unit/test_observability/test_tracing.py
git commit -m "feat(observability): instrument httpx, asyncpg, sqlalchemy, and psycopg for OTEL tracing"
```

## Orchestrator note

Implementer agent stalled (600s watchdog) after `uv add` + implementation + test edits
were already in place, before staging/committing. Orchestrator verified the diff was
additive-only (4 new deps, no version bumps/removals), ran `uv run pytest
tests/unit/test_observability/test_tracing.py` (11 passed) and `just lint` (clean)
directly in the worktree, then completed the commit as
`feat(observability): instrument httpx, asyncpg, sqlalchemy, psycopg` (shortened to fit
the 72-char commit-msg hook limit). Commit: `12e9d19`. Attempt count: 1 (first-pass
success; no TDD retries needed).
