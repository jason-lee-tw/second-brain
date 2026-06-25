# Task: task-1-fix-setup-tracing-tdd-red-green-package

## Plan Section
Fix `setup_tracing()` — add `auto_instrument=True` to `register()` call and add `openinference-instrumentation-langchain` package.

Files:
- apps/backend/tests/unit/test_observability/test_tracing.py
- apps/backend/src/second_brain/observability/tracing.py
- apps/backend/pyproject.toml

## Acceptance Criteria
1. `just test-unit` passes (updated test asserts `auto_instrument=True`)
2. `just lint` and `just type-check` pass clean
3. `openinference-instrumentation-langchain` appears in pyproject.toml

## Attempt 1

### Implementation Plan
- RED: Updated `test_calls_register_with_endpoint_and_default_service_name` in test_tracing.py to assert `auto_instrument=True` in mock_register call.
- GREEN: Added `auto_instrument=True` to `register()` call in `tracing.py`.
- PACKAGE: Added `openinference-instrumentation-langchain==0.1.66` via `uv add`.

### Lint Output
All checks passed!

### Type Check Output
0 errors, 0 warnings, 0 notes

### Test Output
176 passed, 2 warnings in 1.33s

### Outcome
PASS
