# OTEL Tracing Coverage Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DB calls, vector-DB (pgvector) calls, model/embedding calls, and LangGraph checkpointer calls show up as spans in Phoenix, each nested under a per-node span, instead of being invisible black boxes.

**Architecture:** Two independent, additive changes to `apps/backend`'s observability layer only — no business-logic changes. (1) `setup_tracing()` gains explicit `.instrument()` calls for the four raw drivers `auto_instrument=True` can't reach. (2) Every async LangGraph node gets wrapped in a span at the point it's registered with `add_node()`, reusing the existing (currently unused) `trace_node()` decorator after a small fix to its type guard.

**Tech Stack:** OpenTelemetry Python SDK, `opentelemetry-instrumentation-httpx`/`-asyncpg`/`-sqlalchemy`/`-psycopg` (new), Arize Phoenix, LangGraph.

Full context and rationale: [docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md](../specs/2026-07-15-otel-tracing-coverage-fix.md)

## Global Constraints

- Do NOT suppress errors with broad excepts.
- Do NOT install dependencies without flagging first — use `uv add`, never hand-edit `pyproject.toml`/`uv.lock`. (Already flagged and approved: 4 new deps, see Task 2.)
- New code ships with tests for the happy path and 2+ edge cases (TDD).
- Indentation in this codebase is 2 spaces.
- `just lint`, `just format`, `just type-check`, `just test-unit` must all pass clean before this is done.
- Scope is presence + timing only on the new spans — no custom span attributes (row counts, query text, embedding dims).
- Current branch: `fix/000-otel-tracing-coverage` (already created off `main`; spec already committed there). All commits in this plan land on this branch.

---

## Task 1: Let `trace_node()` wrap class-instance nodes

**Files:**
- Modify: `apps/backend/src/second_brain/observability/tracing.py:61-64`
- Test: `apps/backend/tests/unit/test_observability/test_tracing.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `trace_node(name)` now accepts either a plain async function OR any object whose `__call__` is an async method, in addition to what it already accepted. Return type unchanged. Tasks 3 and 4 rely on being able to call `trace_node(node_name)(node_instance)` where `node_instance` is a `BaseNode`/`BaseAgentNode` singleton (e.g. `retrieve_from_rag`, `memory_retrieval_node`).

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/unit/test_observability/test_tracing.py`, inside `class TestTraceNode:` (right after the existing `test_creates_span_with_correct_name` method):

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

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_observability/test_tracing.py::TestTraceNode::test_wraps_callable_instance_with_async_call -v`
Expected: FAIL with `TypeError: trace_node can only decorate async functions, got: <....DummyNode object at ...>`

- [ ] **Step 3: Write minimal implementation**

In `apps/backend/src/second_brain/observability/tracing.py`, the `decorator()` function currently reads:

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

No other lines change — the wrapper body already does `await func(*args, **kwargs)`, which correctly invokes `func.__call__(...)` whether `func` is a plain function or a callable instance.

- [ ] **Step 4: Run tests to verify everything passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_observability/test_tracing.py -v`
Expected: PASS — including `test_raises_type_error_for_sync_function`. (A plain `def sync_node(...)`'s `__call__` is a built-in method-wrapper; `inspect.iscoroutinefunction` still reports `False` for it, so the sync-rejection path is unaffected.)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/observability/tracing.py apps/backend/tests/unit/test_observability/test_tracing.py
git commit -m "fix(observability): let trace_node wrap callable instances, not just functions"
```

---

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

---

## Task 3: Wrap every query-graph node in a span

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

## Task 5: Full verification pass

**Files:** none (verification only).

- [ ] **Step 1: Lint and format**

Run: `just lint && just format`
Expected: no findings, no diff.

- [ ] **Step 2: Type check**

Run: `just type-check`
Expected: zero errors, zero warnings.

- [ ] **Step 3: Full unit suite**

Run: `just test-unit`
Expected: all green.

- [ ] **Step 4: Observe real behavior — query path**

```bash
just up-all
```

Send one query through the real stack:

```bash
curl -s -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "what do you know about me?", "session_id": "trace-check-1"}'
```

Open Phoenix at `http://localhost:6006`, find the trace for this request, and confirm the waterfall now shows, nested under the request span:
- Named node spans: `redact_inbound`, `memory_retrieval_node`, `orchestrator`, one of `rag_retrieval`/`web_research`, `synthesis`, `redact_outbound`, `memory_agent`, `memory_persistence`.
- An `httpx`/`POST` child span under `memory_retrieval_node` (the embedding call to Ollama).
- An `asyncpg`/`SELECT` child span under `memory_retrieval_node` and/or `rag_retrieval` (the pgvector query).
- A `psycopg` span (checkpointer save/load) — likely a sibling of the node spans rather than nested inside one, since the checkpointer runs as part of LangGraph's own state-persistence machinery around node execution, not inside a node body.

If any of these are missing, that's a real gap — go back to Tasks 1-4 and debug; do not mark this done without observing them.

- [ ] **Step 5: Observe real behavior — a memory write**

Send a follow-up message that gives the system something to remember, so `memory_persistence` actually writes:

```bash
curl -s -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "Remember that my favorite programming language is Rust.", "session_id": "trace-check-1"}'
```

In Phoenix, find this request's trace and confirm a SQLAlchemy child span appears under `memory_persistence` (the `LearnedFact` write via `Session(engine)`).

- [ ] **Step 6: Observe real behavior — ingestion path**

Drop a small markdown file into `temp/pending-digest-docs/`, then:

```bash
curl -s -X POST http://localhost:3001/ingest/file
```

In Phoenix, confirm an `ingest` span appears (and no `pick_file` span, by design), with embedding (`httpx`) and DB write spans nested inside it.

- [ ] **Step 7: Commit if any fixes were needed during verification**

If Steps 4-6 surfaced a gap requiring a code fix, make the minimal fix, re-run the relevant `just test-unit` subset, then:

```bash
git add -A
git commit -m "fix(observability): <describe what verification caught>"
```

If no fixes were needed, this step is a no-op — nothing to commit.

## Out of Scope (per spec)

- Custom span attributes (row counts, query text, embedding dims) — presence + timing only.
- Any change to `docs/codebase/001-tech-stack.md` — no new user-facing tech choice is introduced.
