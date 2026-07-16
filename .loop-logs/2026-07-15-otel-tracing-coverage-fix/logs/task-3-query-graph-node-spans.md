# Task 3 Log: Wrap every query-graph node in a span

## Task Context

### Plan Section
### Task 3: Wrap every query-graph node in a span

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/query_graph.py`
- Test: `apps/backend/tests/unit/test_graphs/test_query_graph_build.py`

**Interfaces:**
- Consumes: `trace_node` from `second_brain.observability.tracing` (Task 1's fixed version).
- Produces: no change to `build_query_graph`'s signature or return value — only internal node-registration wiring changes.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/unit/test_graphs/test_query_graph_build.py`. First, add these imports at the top of the file, alongside the existing ones:

```python
import contextlib
```

Then add this test in the "integration tests" section, after the existing `test_build_query_graph_pool_uses_autocommit` test:

```python
@pytest.mark.asyncio
async def test_build_query_graph_wraps_nodes_in_spans():
  """Every node in the compiled graph must emit a named span when invoked."""
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

  mock_pool = AsyncMock()
  mock_pool_class = MagicMock(return_value=mock_pool)
  mock_saver = MagicMock()
  mock_saver.setup = AsyncMock()

  async def fake_redact_inbound(state):
    return {"messages": state["messages"]}

  try:
    with (
      patch("second_brain.graphs.query_graph.AsyncConnectionPool", mock_pool_class),
      patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
      patch("second_brain.graphs.query_graph.redact_inbound", fake_redact_inbound),
    ):
      MockSaver.return_value = mock_saver
      from second_brain.graphs.query_graph import build_query_graph

      graph, _pool = await build_query_graph(
        "postgresql://fake:fake@localhost:5432/test"
      )
      state: SecondBrainState = {
        "session_id": "s1",
        "messages": [],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
      }
      # routing_decision="neither" routes straight to synthesis, which needs a
      # real/mocked LLM; we only assert on redact_inbound's span below, so
      # suppress whatever downstream failure that path hits (e.g. missing
      # ANTHROPIC_API_KEY) rather than mocking every remaining node.
      with contextlib.suppress(Exception):
        await graph.ainvoke(state, config={"configurable": {"thread_id": "t1"}})
  finally:
    trace.set_tracer_provider(original_provider)

  span_names = {s.name for s in exporter.get_finished_spans()}
  assert "redact_inbound" in span_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_graphs/test_query_graph_build.py::test_build_query_graph_wraps_nodes_in_spans -v`
Expected: FAIL — `span_names` is an empty set (no node is wrapped in a span yet).

- [ ] **Step 3: Write minimal implementation**

In `apps/backend/src/second_brain/graphs/query_graph.py`, add this import alongside the existing `second_brain` imports:

```python
from second_brain.observability.tracing import trace_node
```

Then replace the `# Nodes` block:

```python
  workflow.add_node("redact_inbound", redact_inbound)
  workflow.add_node("memory_retrieval_node", memory_retrieval_node)
  workflow.add_node("memory_agent", memory_agent_node)
  workflow.add_node("memory_persistence", memory_persistence_node)
  workflow.add_node("orchestrator", route_query)
  workflow.add_node("rag_retrieval", retrieve_from_rag)
  workflow.add_node("web_research", search_web)
  workflow.add_node("synthesis", synthesize_answer)
  workflow.add_node("redact_outbound", redact_outbound)
```

with:

```python
  workflow.add_node("redact_inbound", trace_node("redact_inbound")(redact_inbound))
  workflow.add_node(
    "memory_retrieval_node", trace_node("memory_retrieval_node")(memory_retrieval_node)
  )
  workflow.add_node("memory_agent", trace_node("memory_agent")(memory_agent_node))
  workflow.add_node(
    "memory_persistence", trace_node("memory_persistence")(memory_persistence_node)
  )
  workflow.add_node("orchestrator", trace_node("orchestrator")(route_query))
  workflow.add_node("rag_retrieval", trace_node("rag_retrieval")(retrieve_from_rag))
  workflow.add_node("web_research", trace_node("web_research")(search_web))
  workflow.add_node("synthesis", trace_node("synthesis")(synthesize_answer))
  workflow.add_node("redact_outbound", trace_node("redact_outbound")(redact_outbound))
```

- [ ] **Step 4: Run tests to verify everything passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_graphs/test_query_graph_build.py -v`
Expected: PASS, all tests in the file. The pre-existing tests patch node names (e.g. `AsyncConnectionPool`, `AsyncPostgresSaver`) before `build_query_graph()` runs, so wrapping happens around whatever object is bound to that name at build time — mock or real — and those tests are unaffected.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/graphs/query_graph.py apps/backend/tests/unit/test_graphs/test_query_graph_build.py
git commit -m "feat(observability): wrap query graph nodes in per-node spans"
```

---

## Attempt 1 — 2026-07-15T06:58:43Z

### Implementation Plan
- Add `test_build_query_graph_wraps_nodes_in_spans` to the test file, confirm it fails RED
- Wrap all 9 query-graph nodes in `trace_node(name)` per the plan's literal instructions
- Run the full test file, diagnose and fix any regressions surfaced by wrapping real node objects
- Run `just lint` and `just test-unit`

### Files Changed
- modified `apps/backend/src/second_brain/graphs/query_graph.py` — wraps the 7 async query-graph nodes (memory_retrieval_node, memory_agent, memory_persistence, orchestrator, rag_retrieval, web_research, synthesis) in `trace_node(name)`; leaves `redact_inbound`/`redact_outbound` unwrapped
- modified `apps/backend/tests/unit/test_graphs/test_query_graph_build.py` — adds `test_build_query_graph_wraps_nodes_in_spans`, rewritten from the plan's literal version (see Key Decisions)

### New Tests
- `test_build_query_graph_wraps_nodes_in_spans`

### Key Decisions
- **Did not wrap `redact_inbound`/`redact_outbound` in `trace_node`.** The plan's Step 3 instructs wrapping all 9 nodes unconditionally. Diagnosis showed `RedactInboundNode.__call__`/`RedactOutboundNode.__call__` (`apps/backend/src/second_brain/nodes/pii_redaction.py`) are genuinely **sync** (pure regex-based PII redaction, no I/O) — unlike every other query-graph node, which is `async def __call__`. `trace_node` (fixed in Task 1) only accepts async callables and raises `TypeError` at decoration time for sync ones. Wrapping them as literally instructed broke 4 pre-existing tests (`test_build_query_graph_returns_compiled_graph`, `test_build_query_graph_calls_pool_open`, `test_build_query_graph_calls_checkpointer_setup`, `test_build_query_graph_pool_uses_autocommit`) and would crash `build_query_graph()` in production. Leaving them unwrapped mirrors Task 4's own established precedent for `pick_file_node` in the ingestion graph ("sync and does no I/O — not wrapped ... nothing to trace inside pure state slicing anyway"). This is a genuine gap in the plan text (Task 3's section didn't account for the PII nodes being sync), not a deviation for convenience.
- **Rewrote the new test's body**, keeping its intent (assert `add_node()` wraps a real node in a span) but changing the mechanism, for two independent reasons surfaced during the RED→GREEN loop:
  1. The plan's literal test calls `graph.ainvoke()` against a `StateGraph` compiled with a mocked `AsyncPostgresSaver`. LangGraph's Pregel executor awaits several checkpointer methods beyond `.setup()` (`aget_tuple`, internal version comparisons, etc.) that a generic `MagicMock`/`AsyncMock` can't faithfully emulate — three different `TypeError`s surfaced in sequence (non-awaitable MagicMock attrs, `MagicMock < int` comparison inside checkpoint migration, `type(coroutine)()` inside version-null calculation) before concluding the full Pregel loop is not a viable path to test node wrapping through a mocked checkpointer.
  2. Fix: invoke each node's runnable directly via `graph.nodes[name].ainvoke(state)` (LangGraph's public per-node access on the compiled graph) instead of the whole-graph `ainvoke()`. This bypasses the checkpoint loop entirely and isolates exactly what the test needs to check. Verified empirically with a standalone script before editing the test file.
  3. Since `redact_inbound` is asserted as *unwrapped* now (not wrapped, per the decision above), the test also asserts `"redact_inbound" not in span_names` after invoking it directly with a valid one-message state — this exercises the real (unpatched) sync `RedactInboundNode` and proves it produces no span, mirroring Task 4's `test_graph_emits_span_for_ingest_node_but_not_pick_file` pattern.
  4. Kept the OTel `TracerProvider` `Once`-latch reset/restore inline in the test (`opentelemetry.trace._TRACER_PROVIDER` / `_TRACER_PROVIDER_SET_ONCE._done`) — same technique already established in `tests/unit/test_observability/conftest.py`'s autouse fixture, but inlined here since this test lives in a different test directory not covered by that conftest.

### Lint Output
PASS

### Test Output
PASS (224 passed, 1 new — full `just test-unit` suite; 10 passed in test_query_graph_build.py specifically)

### Commit
`a410504`

### Outcome: success
