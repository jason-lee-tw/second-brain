# Task 1 Log: Trace Node Callable Instances

## Task Context

### Plan Section

**Files:**
- Modify: `apps/backend/src/second_brain/observability/tracing.py:61-64`
- Test: `apps/backend/tests/unit/test_observability/test_tracing.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `trace_node(name)` now accepts either a plain async function OR any object whose `__call__` is an async method, in addition to what it already accepted. Return type unchanged. Tasks 3 and 4 (not your concern — separate agents, separate worktrees, sequenced after you) rely on being able to call `trace_node(node_name)(node_instance)` where `node_instance` is a `BaseNode`/`BaseAgentNode` singleton.

Steps (do these in order, exactly):

1. Add to `apps/backend/tests/unit/test_observability/test_tracing.py`, inside `class TestTraceNode:` (right after the existing `test_creates_span_with_correct_name` method):

```python
  @pytest.mark.asyncio
  async def test_wraps_callable_instance_with_async_call(self, in_memory_tracer):
    """trace_node accepts an object whose __call__ is async, not just a bare function."""

    class DummyNode:
      async def __call__(self, state: dict) -> dict:
        return {"seen": state}

    traced = trace_node("instance-node")(DummyNode())
    result = await traced({"x": 1})

    assert result == {"seen": {"x": 1}}
    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "instance-node"
```

2. Run: `cd apps/backend && uv run pytest tests/unit/test_observability/test_tracing.py::TestTraceNode::test_wraps_callable_instance_with_async_call -v` (adjust relative path since you're already in the worktree root — the command is `cd apps/backend && uv run pytest ...` from your worktree root). Confirm it FAILS with `TypeError: trace_node can only decorate async functions, got: <....DummyNode object at ...>`. If it fails for a different reason, that's a real bug — stop and diagnose, don't paper over it.

3. In `apps/backend/src/second_brain/observability/tracing.py`, the `decorator()` function currently reads:

```python
  def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
    if not inspect.iscoroutinefunction(func):
      raise TypeError(f"trace_node can only decorate async functions, got: {func!r}")
```

Replace those two lines with:

```python
  def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
    is_async = inspect.iscoroutinefunction(func) or inspect.iscoroutinefunction(
      getattr(func, "__call__", None)
    )
    if not is_async:
      raise TypeError(f"trace_node can only decorate async functions, got: {func!r}")
```

No other lines change — the wrapper body already does `await func(*args, **kwargs)`.

4. Run: `cd apps/backend && uv run pytest tests/unit/test_observability/test_tracing.py -v` — expect ALL PASS, including `test_raises_type_error_for_sync_function`.

5. Run `<lint_cmd>` (`just lint`, from worktree root) — must exit 0.

6. Run `<test_cmd>` (`just test-unit`, from worktree root) — must exit 0.

## Orchestrator note

Implementer agent stalled (600s watchdog) mid-commit after having already staged the
correct implementation and test changes. Orchestrator verified `just lint` and the
full `test_tracing.py` suite (11 passed) directly in the worktree, then completed the
commit. Only the commit-message subject line needed adjustment (78 chars exceeded the
72-char commit-msg hook limit): `fix(observability): let trace_node wrap callable instances`.
Commit: `e7c3bcd`. Attempt count: 1 (first-pass success; no TDD retries needed).
