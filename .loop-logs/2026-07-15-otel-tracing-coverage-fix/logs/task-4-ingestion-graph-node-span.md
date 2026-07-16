# Task 4 Log: Wrap the ingestion-graph's async node in a span

## Task Context

### Plan Section
## Task 4: Wrap the ingestion-graph's async node in a span

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/ingestion_graph.py`
- Test: `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py`

**Interfaces:**
- Consumes: `trace_node` from `second_brain.observability.tracing`.
- Produces: no change to `build_ingestion_graph`'s signature or return value.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py`, at the end of the file:

```python
@pytest.mark.asyncio
async def test_graph_emits_span_for_ingest_node_but_not_pick_file():
  """The 'ingest' node must emit a span; 'pick_file' (sync, no I/O) must not."""
  from opentelemetry import trace
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
  )

  exporter = InMemorySpanExporter()
  provider = TracerProvider()
  provider.add_span_processor(SimpleSpanProcessor(exporter))
  original_provider = trace.get_tracer_provider()
  trace.set_tracer_provider(provider)

  async def fake_ingest_node(state):
    filename = state["in_progress"]
    return {
      "processed": state["processed"] + [filename],
      "in_progress": None,
      "retry_queue": [],
    }

  try:
    with patch(_PATCH_TARGET, fake_ingest_node):
      from second_brain.graphs.ingestion_graph import build_ingestion_graph

      graph = build_ingestion_graph()
      await graph.ainvoke(_make_state(files=["a.md"]))
  finally:
    trace.set_tracer_provider(original_provider)

  span_names = [s.name for s in exporter.get_finished_spans()]
  assert "ingest" in span_names
  assert "pick_file" not in span_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_graphs/test_ingestion_graph.py::test_graph_emits_span_for_ingest_node_but_not_pick_file -v`
Expected: FAIL — `span_names` does not contain `"ingest"`.

- [ ] **Step 3: Write minimal implementation**

In `apps/backend/src/second_brain/graphs/ingestion_graph.py`, add this import alongside the existing `second_brain` imports:

```python
from second_brain.observability.tracing import trace_node
```

Then replace:

```python
  builder.add_node("pick_file", pick_file_node)
  builder.add_node("ingest", ingestion_agent_node)
```

with:

```python
  # pick_file_node is sync and does no I/O — not wrapped (trace_node only
  # accepts async callables; nothing to trace inside pure state slicing anyway).
  builder.add_node("pick_file", pick_file_node)
  builder.add_node("ingest", trace_node("ingest")(ingestion_agent_node))
```

- [ ] **Step 4: Run tests to verify everything passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_graphs/test_ingestion_graph.py -v`
Expected: PASS, all tests including the new one.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/graphs/ingestion_graph.py apps/backend/tests/unit/test_graphs/test_ingestion_graph.py
git commit -m "feat(observability): wrap ingestion graph's ingest node in a span"
```

---

## Attempt 1 — 2026-07-15T06:52:44Z

### Implementation Plan
- Verified `_PATCH_TARGET` and `_make_state` already exist in the test file exactly as the plan expected — no adaptation needed.
- Added `test_graph_emits_span_for_ingest_node_but_not_pick_file` verbatim from the plan; confirmed it FAILS for the expected reason (`"ingest" not in []`).
- Wrapped `ingestion_agent_node` with `trace_node("ingest")` in `build_ingestion_graph`, added the `trace_node` import, left `pick_file_node` unwrapped per plan comment.
- Ran the target test file (5/5 pass), then full workspace lint and full `just test-unit`.

### Files Changed
- modified `apps/backend/src/second_brain/graphs/ingestion_graph.py` — wraps `ingest` node with `trace_node("ingest")`, imports `trace_node`
- modified `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py` — added `test_graph_emits_span_for_ingest_node_but_not_pick_file`
- created `apps/backend/tests/unit/test_graphs/conftest.py` — autouse fixture resetting OTel's global `TracerProvider` Once-guard state between tests in this directory

### New Tests
- `test_graph_emits_span_for_ingest_node_but_not_pick_file`

### Key Decisions
- The plan's verbatim test snippet swaps the global OTel `TracerProvider` via the public `trace.set_tracer_provider()` API and restores it in a `finally` block. OTel's SDK guards the global provider with a one-shot `Once` lock: the first ever call to `set_tracer_provider()` in the process succeeds, but any subsequent call (including the test's own "restore" in `finally`) is silently a no-op (with a `WARNING ... Overriding of current TracerProvider is not allowed` log line). Running only the new test or only the file, this is invisible — my test happens to be the *first* thing in the whole pytest session to touch the global provider, so its own swap succeeds. But it permanently trips the Once-guard for every test that runs afterward in the same session. This broke 5 pre-existing tests in `apps/backend/tests/unit/test_observability/test_tracing.py` when running the full suite (`just test-unit`), each asserting spans that never landed in their own in-memory exporter because the global provider was stuck on my test's now-inert one. Confirmed via isolation: `test_tracing.py` alone passes 12/12; only fails as part of the full suite. Root cause and precedented fix already exist in the codebase: `apps/backend/tests/unit/test_observability/conftest.py` has an autouse `_reset_otel_tracer_provider` fixture that bypasses the Once-guard by directly resetting the private `_TRACER_PROVIDER` / `_TRACER_PROVIDER_SET_ONCE._done` attributes — but it is scoped only to its own directory (pytest conftest fixtures apply per-directory-tree), so it does not cover `test_graphs/`. Fix: added an identical autouse fixture in a new `apps/backend/tests/unit/test_graphs/conftest.py`, scoped to just this directory, rather than editing the shared `test_observability/conftest.py` or a top-level `tests/unit/conftest.py` — this keeps the fix minimal and avoids touching files that sibling parallel-worktree tasks (e.g. task-3's query-graph node-span test, which likely hits the identical issue) may also be editing.

### Lint Output
PASS

### Test Output
PASS (224 passed, 1 new)

### Commit
`13ff671`

### Outcome: success
