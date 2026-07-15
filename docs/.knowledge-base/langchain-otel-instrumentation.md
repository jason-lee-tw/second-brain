# LangChain OTEL Instrumentation

A fix enabling Phoenix `auto_instrument=True` so LangChain/LangGraph internals emit `LLM`/`CHAIN`/`TOOL` OTEL spans, closing a gap where only FastAPI HTTP spans were visible.

## Key Concepts

- **Symptom:** Phoenix only showed FastAPI HTTP spans of kind `UNKNOWN` for `/query` requests — zero `LLM`, `CHAIN`, or `TOOL` spans appeared, so LangChain and LangGraph node activity was invisible in traces. Confirmed via trace `88001bbe15d4bc3641ab5da122f45f75`, whose span tree contained only `POST /query` and its `http receive`/`http send` children, with no LangChain-level spans nested inside.
- **Root cause — two independent gaps:**
  1. Missing package: `openinference-instrumentation-langchain` (the OpenInference instrumentor that patches LangChain's callback system to emit OTEL spans) was not declared in `apps/backend/pyproject.toml`.
  2. Auto-instrumentation not enabled: `phoenix.otel.register()` was called with `auto_instrument=False` (the default), so even with the package installed it would not activate.
- **Asymmetry that revealed the bug:** `FastAPIInstrumentor.instrument_app(app)` is explicitly wired for HTTP spans in `main.py`, but there was no equivalent explicit wiring for LangChain — explaining why HTTP spans appeared but LLM/CHAIN spans didn't.
- **The fix:** add `openinference-instrumentation-langchain` as a dependency, and change the `register()` call inside `setup_tracing()` (in `apps/backend/src/second_brain/observability/tracing.py`) to pass `auto_instrument=True` instead of the default `False`. The existing lifespan/tracing setup in `main.py` is otherwise unchanged.
- **Why `auto_instrument=True` is sufficient:** `phoenix.otel.register(auto_instrument=True)` auto-discovers and activates *all* installed `openinference-instrumentation-*` packages at startup — no manual `LangChainInstrumentor().instrument()` call is needed. This generalizes for free to any future `openinference-instrumentation-*` package added to the backend.
- **Files touched:** `apps/backend/pyproject.toml` (add dependency), `apps/backend/src/second_brain/observability/tracing.py` (enable `auto_instrument=True`), `apps/backend/tests/unit/test_observability/test_tracing.py` (assert the new flag), `docs/codebase/001-tech-stack.md` (document the new dependency in the Observability row).
- **TDD sequencing:** red — update `TestSetupTracing.test_calls_register_with_endpoint_and_default_service_name` to expect `mock_register.assert_called_once_with(project_name="second-brain", endpoint="http://localhost:4317", auto_instrument=True)` and confirm it fails first (register is mocked, so the test drives the contract before the real package exists); green — edit `setup_tracing()`'s final `register()` call to include `auto_instrument=True` and confirm the target test (and full suite) pass; only then add the runtime dependency via `uv add openinference-instrumentation-langchain --project apps/backend` (run from the workspace root), verified with `grep "openinference" apps/backend/pyproject.toml`, and re-run `just test-unit`.
- **Acceptance criteria:** `just test-unit` passes with the updated assertion; `just lint` and `just type-check` pass clean; after `just up-all`, an actual `/query` request produces Phoenix spans with `span_kind=LLM` and `span_kind=CHAIN` visible in the `second-brain` Phoenix project — runtime verification, not just unit tests.
- **Runtime verification steps:** boot with `just up-all`; send `curl -s -X POST http://localhost:3001/query -H "Content-Type: application/json" -d '{"message": "what do you know?", "session_id": "test-otel"}' | jq .`; open Phoenix UI at `http://localhost:6006`, navigate to project `second-brain`, and confirm the latest trace now contains `LLM`/`CHAIN` spans.
- **Process constraints:** work on branch `fix/000-langchain-otel-spans`; use `uv add`, never hand-edit `uv.lock`; run `just lint`, `just type-check`, `just test-unit` before every commit; Conventional Commits enforced by `.hooks/commit-msg` (e.g. `fix(observability): enable LangChain OTEL instrumentation via auto_instrument`, `docs: note LangChain OTEL instrumentation in tech-stack`).

## Sources

- Fix Missing LangChain OTEL Spans Implementation Plan — `docs/superpowers/plans/2026-06-25-langchain-otel-instrumentation.md`
- Spec: Fix Missing LangChain OTEL Spans in Phoenix — `docs/superpowers/specs/2026-06-25-langchain-otel-instrumentation.md`

## Related Topics

- [[otel-phoenix-tracing]]
- [[dependency-management]]
- [[tech-stack]]
