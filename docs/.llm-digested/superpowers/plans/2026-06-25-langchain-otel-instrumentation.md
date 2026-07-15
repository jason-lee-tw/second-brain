# Fix Missing LangChain OTEL Spans Implementation Plan

Source: docs/superpowers/plans/2026-06-25-langchain-otel-instrumentation.md
Primary-Topic: langchain-otel-instrumentation
Secondary-Topics: phoenix-tracing, dependency-management

## Key Concepts

- Goal: surface LangChain LLM/CHAIN/TOOL spans in Arize Phoenix by adding the `openinference-instrumentation-langchain` package and enabling `auto_instrument=True` in `setup_tracing()`.
- Root cause / architecture: `phoenix.otel.register(auto_instrument=True)` auto-discovers and activates all installed `openinference-instrumentation-*` packages at startup — no manual `LangChainInstrumentor().instrument()` call is needed.
- The existing lifespan + tracing setup in `main.py` stays unchanged; only the `register()` call inside `setup_tracing()` gains the new kwarg.
- Tech stack involved: `openinference-instrumentation-langchain` (new dependency) and `arize-phoenix-otel>=0.8` (already installed).
- Companion spec lives at `docs/superpowers/specs/2026-06-25-langchain-otel-instrumentation.md`.
- Global constraints for implementers: use `uv add`, never hand-edit `uv.lock`; Conventional Commits enforced by `.hooks/commit-msg`; work on branch `fix/000-langchain-otel-spans`; run `just lint`, `just type-check`, `just test-unit` before every commit; Python ≥ 3.12.
- File map (four files touched):
  - `apps/backend/pyproject.toml` — add `openinference-instrumentation-langchain` dependency.
  - `apps/backend/src/second_brain/observability/tracing.py` — add `auto_instrument=True` to the `register()` call.
  - `apps/backend/tests/unit/test_observability/test_tracing.py` — update `test_calls_register_with_endpoint_and_default_service_name` to assert `auto_instrument=True`.
  - `docs/codebase/001-tech-stack.md` — note LangChain instrumentation in the Observability row.
- Task 1 follows strict TDD red → green → package sequencing:
  - Red: update `TestSetupTracing.test_calls_register_with_endpoint_and_default_service_name` to expect `mock_register.assert_called_once_with(project_name="second-brain", endpoint="http://localhost:4317", auto_instrument=True)`. Tests mock `register`, so they don't need the real package installed yet — the test drives the contract before the dependency is added.
  - Confirm the test fails first (`just test-unit -k "test_calls_register_with_endpoint_and_default_service_name"`), expecting `AssertionError` because the `auto_instrument` kwarg is absent from the current implementation.
  - Green: edit `setup_tracing()` in `tracing.py` so its final `register()` call becomes `register(project_name="second-brain", endpoint=phoenix_collection_endpoint, auto_instrument=True)`.
  - Run the full unit suite (`just test-unit`) to confirm the target test passes and nothing else breaks.
  - Only after green, add the runtime dependency: `uv add openinference-instrumentation-langchain --project apps/backend` (run from the workspace root, `ai-learning-milestone/`). Verify via `grep "openinference" apps/backend/pyproject.toml`. Rationale: `auto_instrument=True` needs the package installed at runtime to actually discover and activate the LangChain instrumentor, but tests pass without it because `register` is mocked.
  - Re-run `just test-unit` after adding the package to confirm the dependency addition doesn't break anything.
  - Gate before commit: `just lint && just type-check` must show no errors/warnings.
  - Commit message: `fix(observability): enable LangChain OTEL instrumentation via auto_instrument`, staging exactly `apps/backend/pyproject.toml`, `uv.lock`, `apps/backend/src/second_brain/observability/tracing.py`, `apps/backend/tests/unit/test_observability/test_tracing.py`.
- Task 2 updates documentation only:
  - Change the Observability row in `docs/codebase/001-tech-stack.md` from `Arize Phoenix (OTEL) — UI at localhost:6006` to also mention `openinference-instrumentation-langchain` for LangChain/LangGraph spans.
  - Commit with message: `docs: note LangChain OTEL instrumentation in tech-stack`.
- Runtime verification steps (after both tasks land):
  - Boot the stack with `just up-all`.
  - Send a test query: `curl -s -X POST http://localhost:3001/query -H "Content-Type: application/json" -d '{"message": "what do you know?", "session_id": "test-otel"}' | jq .`
  - Open Phoenix UI at `http://localhost:6006`, navigate to project `second-brain`, find the latest trace.
  - Confirm the trace contains spans with `span_kind = LLM` and `span_kind = CHAIN` — proof that LangChain/LangGraph internals are now visible in Phoenix (previously missing before this fix).
- Plan is annotated for agentic workers to use the `superpowers:subagent-driven-development` or `superpowers:executing-plans` skill, executing task-by-task via checkbox tracking.
