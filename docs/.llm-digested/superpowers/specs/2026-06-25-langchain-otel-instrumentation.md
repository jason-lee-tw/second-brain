# Spec: Fix Missing LangChain OTEL Spans in Phoenix

Source: docs/superpowers/specs/2026-06-25-langchain-otel-instrumentation.md
Primary-Topic: opentelemetry-instrumentation
Secondary-Topics: phoenix-tracing, langchain-callbacks

## Key Concepts

- **Symptom**: Phoenix only shows FastAPI HTTP spans of kind `UNKNOWN` when `/query` is called; zero `LLM`, `CHAIN`, or `TOOL` spans appear, so LangChain and LangGraph node activity is invisible in traces.
- Confirmed via trace `88001bbe15d4bc3641ab5da122f45f75`, whose span tree only contains `POST /query` and its `http receive`/`http send` children — no LangChain-level spans nested inside.
- **Root cause has two independent gaps**:
  1. Missing package: `openinference-instrumentation-langchain` (the OpenInference instrumentor that patches LangChain's callback system to emit OTEL spans) is not declared in `pyproject.toml`.
  2. Auto-instrumentation not enabled: `phoenix.otel.register()` is called with `auto_instrument=False` (the default), so even if the package were installed it would not activate.
- `FastAPIInstrumentor.instrument_app(app)` is explicitly wired for HTTP spans, but there is no equivalent explicit wiring for LangChain — this asymmetry is why HTTP spans appear but LLM/CHAIN spans don't.
- **Fix part 1 — add dependency**: add `openinference-instrumentation-langchain` to `apps/backend/pyproject.toml` dependencies; install via `uv sync --all-extras` (or `just init`).
- **Fix part 2 — enable auto-instrumentation**: in `src/second_brain/observability/tracing.py`, change the `register()` call's `setup_tracing()` to pass `auto_instrument=True` instead of the default `False`.
- `auto_instrument=True` causes Phoenix's `register()` to discover and activate *all* installed `openinference-instrumentation-*` packages at startup automatically — no separate manual `LangChainInstrumentor().instrument()` call is needed.
- **Acceptance criteria**:
  1. `just test-unit` passes, with the test for `setup_tracing()` updated to assert `auto_instrument=True`.
  2. `just lint` and `just type-check` pass clean.
  3. After `just up-all`, an actual `/query` request produces Phoenix spans with `span_kind=LLM` and `span_kind=CHAIN` visible in the `second-brain` Phoenix project (runtime verification, not just unit tests).
- **Files changed**: `apps/backend/pyproject.toml` (add dependency), `apps/backend/src/second_brain/observability/tracing.py` (enable `auto_instrument=True`), `apps/backend/tests/unit/test_observability/test_tracing.py` (assert new flag), `docs/codebase/001-tech-stack.md` (document the new dependency).
- Broader implication: any future `openinference-instrumentation-*` package added to the backend will be auto-activated for free once `auto_instrument=True` is set — this is a one-time fix that generalizes to other instrumented libraries, not just LangChain.
