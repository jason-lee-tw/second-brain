# Task R2-1 Log: Stop trace_node leaking node instance state via functools.wraps

## Task Context

### Plan Section
`apps/backend/src/second_brain/observability/tracing.py`, in `trace_node`'s
`decorator()` function, has `@functools.wraps(func)` applied to the wrapper. `func` can
now be either a plain async function OR a callable class instance (since the Task-1 fix
that widened the `is_async` guard). `functools.wraps`/`functools.update_wrapper`'s
default `WRAPPER_UPDATES = ('__dict__',)` unconditionally does
`wrapper.__dict__.update(wrapped.__dict__)` — for a stateful instance (e.g. any
`BaseAgentNode` subclass, which carries `self._agent` etc.), this merges the instance's
instance attributes onto the returned wrapper *function*, leaking internal state onto
an object that's supposed to just be a callable. Verified empirically:
```python
traced = trace_node('orchestrator')(route_query)  # route_query is a BaseAgentNode instance
traced.__dict__.keys()  # -> ['_agent', '_structured_llm', '__wrapped__'] — leaked!
```
This doesn't currently break anything (nothing reads these attributes off the wrapper),
but it's a real, demonstrated defect: `functools.wraps` is being asked to do more than
intended (name/qualname/doc preservation + `__wrapped__` for introspection), and its
default behavior over-applies for a non-function callable.

Fix: change `@functools.wraps(func)` to `@functools.wraps(func, updated=())` on the
`wrapper` function inside `decorator()`. This keeps `WRAPPER_ASSIGNMENTS` (name,
qualname, doc, module, etc.) and `__wrapped__` intact, while dropping the `__dict__`
merge.

### Acceptance Criteria
- AC-1: `trace_node(...)( <callable instance with instance state> )` returns a wrapper
  whose `__dict__` does not contain the wrapped instance's attributes (e.g.
  `secret_state`).
- AC-2: Existing behavior (span creation, name/qualname preservation via
  `functools.wraps`, exception propagation, async callable-instance support) is
  unchanged — all pre-existing tests in `test_tracing.py` continue to pass.
- AC-3: `just test-unit` passes with 226 passed (225 pre-existing + 1 new regression
  test).
- AC-4: `just lint` passes with no changes.

---

## Attempt 1 — 2026-07-16T00:00:00Z

### Implementation Plan
- Add `test_does_not_leak_instance_state_onto_wrapper` to
  `TestTraceNode` in `apps/backend/tests/unit/test_observability/test_tracing.py`,
  using a `StatefulDummyNode` helper with `__init__`-set instance state (unlike the
  existing `DummyNode` helper, which has no `__dict__` content to leak).
- Run the new test against the current (buggy) code to confirm it fails.
- Apply the fix: `@functools.wraps(func)` -> `@functools.wraps(func, updated=())` in
  `apps/backend/src/second_brain/observability/tracing.py`.
- Re-run the test file, then the full unit suite, then lint.

### Files Changed
- modified `apps/backend/tests/unit/test_observability/test_tracing.py` — added
  `test_does_not_leak_instance_state_onto_wrapper` to `TestTraceNode`
- modified `apps/backend/src/second_brain/observability/tracing.py` — changed
  `@functools.wraps(func)` to `@functools.wraps(func, updated=())` on the `wrapper`
  function inside `trace_node`'s `decorator()`

### New Tests
- `test_does_not_leak_instance_state_onto_wrapper`

### Key Decisions
- Used `updated=()` (rather than e.g. deleting the leaked attribute post-hoc, or
  switching away from `functools.wraps` entirely) because `WRAPPER_ASSIGNMENTS` (name,
  qualname, doc, module, `__wrapped__`) is exactly what's needed for introspection and
  logging, and `updated=()` is the documented, minimal way to opt out of the `__dict__`
  merge without touching assignment behavior.
- Confirmed regression test fails pre-fix (`AssertionError: assert 'secret_state' not
  in {'secret_state': 'should-not-leak', '__wrapped__...`) before applying the fix, per
  TDD requirement.

### Lint Output
PASS
(`just lint` -> "All checks passed!")

### Test Output
PASS (226 passed, 1 new)
(`just test-unit` -> "226 passed, 2 warnings in 1.69s"; targeted run of
`tests/unit/test_observability/test_tracing.py::TestTraceNode` -> 13 passed, including
the new test and the pre-existing `test_wraps_callable_instance_with_async_call` and
`test_raises_type_error_for_sync_function`)

### Commit
`24d6e1d`

### Outcome: success
