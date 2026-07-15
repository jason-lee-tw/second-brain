# Spec: Extend OTEL Tracing to DB, Vector-DB, and Model/Embedding Calls

**Date:** 2026-07-15

---

## Problem

`setup_tracing()` (added in [2026-06-25-langchain-otel-instrumentation.md](./2026-06-25-langchain-otel-instrumentation.md)) makes LangChain/LLM activity visible in Phoenix, but every other component still produces zero spans:

- Ollama embedding calls (raw `httpx`, not routed through LangChain)
- pgvector/Postgres reads (raw `asyncpg`)
- Postgres writes (`SQLModel Session(engine)` → SQLAlchemy/psycopg2)
- LangGraph checkpointer save/load (`psycopg_pool.AsyncConnectionPool`, psycopg3)
- Every LangGraph node boundary itself (no per-node span at all)

Developers can see that `/query` took N seconds and that an LLM call happened somewhere inside it, but not which node, which DB query, or which embedding call the time went to.

---

## Root Cause

Two independent gaps:

1. **`auto_instrument=True` only covers `openinference-instrumentation-*` packages.** Confirmed in `pyproject.toml` — the only one installed is `openinference-instrumentation-langchain`. That instruments calls made *through LangChain* only (in this codebase: the `ChatAnthropic` call in `nodes/base_node/agents/claude_agent.py`). It has no visibility into raw `httpx`, `asyncpg`, or SQLAlchemy calls, because those aren't LangChain-mediated and no generic `opentelemetry-instrumentation-*` package for them is installed either.

2. **The node-level span mechanism was built but never wired up.** `observability/tracing.py::trace_node()` is a fully implemented decorator meant to wrap a LangGraph node in a span. `grep -rn "trace_node" src/` finds only its own definition and docstring — zero call sites. `BaseNode`/`BaseAgentNode` (`nodes/base_node/`) have no span wrapping either. So even the node boundary — one level below the HTTP request span — is a black box.

Confirmed call sites for each affected path:

| Category | File(s) | Driver |
|---|---|---|
| Model/embedding calls | `services/embeddings.py`, `nodes/rag_retrieval.py::_embed_query` | raw `httpx.AsyncClient` → Ollama |
| Vector DB reads | `db/pool.py` + `nodes/rag_retrieval.py`, `nodes/memory_retrieval.py`, `nodes/memory_persistence.py` | raw `asyncpg` |
| DB writes | `nodes/memory_persistence.py` via `db/session.py`'s `engine` | `SQLModel Session(engine)` → SQLAlchemy/psycopg2 |
| Checkpointer save/load | `graphs/query_graph.py` (`AsyncPostgresSaver`) | `psycopg_pool.AsyncConnectionPool` (psycopg3) |

---

## Fix

### 1. Add dependencies

```
opentelemetry-instrumentation-httpx
opentelemetry-instrumentation-asyncpg
opentelemetry-instrumentation-sqlalchemy
opentelemetry-instrumentation-psycopg
```

All four verified present on PyPI at `0.64b0`. Added via `uv add` in `apps/backend/` — never hand-edited into `pyproject.toml`/`uv.lock`. Same trust tier as the already-installed `opentelemetry-instrumentation-fastapi`: pure span-emission shims, no new runtime behavior.

### 2. Instrument the raw drivers in `setup_tracing()`

In `src/second_brain/observability/tracing.py`, after `register(...)` returns the provider, call each instrumentor's `.instrument()` with no arguments (all four patch at the class level — `Engine`, `Connection`, `AsyncClient` — so it doesn't matter whether pools/engines/clients were constructed before or after this call):

```python
provider = register(
  project_name="second-brain",
  endpoint=phoenix_collection_endpoint,
  auto_instrument=True,
)
HTTPXClientInstrumentor().instrument()
AsyncPGInstrumentor().instrument()
SQLAlchemyInstrumentor().instrument()
PsycopgInstrumentor().instrument()
return provider
```

Scope is presence + timing only — no custom span attributes (row counts, query text, embedding dimensions). If deeper attributes are wanted later, that's a separate spec.

### 3. Fix `trace_node()` to accept callable class instances

All LangGraph nodes in this codebase are singleton instances of `BaseNode`/`BaseAgentNode` subclasses (e.g. `retrieve_from_rag = RagRetrievalNode()`), not bare functions. `trace_node`'s guard (`inspect.iscoroutinefunction(func)`) is `False` for an instance even when its `__call__` is `async def`.

Fix the guard in `trace_node`'s `decorator()`:

```python
is_async = inspect.iscoroutinefunction(func) or inspect.iscoroutinefunction(
  getattr(func, "__call__", None)
)
if not is_async:
  raise TypeError(f"trace_node can only decorate async functions, got: {func!r}")
```

The wrapper body (`await func(*args, **kwargs)`) needs no change — it already invokes `__call__` correctly whether `func` is a function or a callable instance. This does not weaken the existing sync-rejection behavior: a plain `def sync_node(...)`'s `__call__` is a built-in method-wrapper, which `iscoroutinefunction` still reports `False` for.

### 4. Wrap every async node at its `add_node()` call site

In `graphs/query_graph.py` and `graphs/ingestion_graph.py`, wrap each node where it's registered:

```python
workflow.add_node("rag_retrieval", trace_node("rag_retrieval")(retrieve_from_rag))
```

Chosen over the alternative of making `BaseNode`/`BaseAgentNode.__call__` concrete (which would require touching both ABCs plus a mechanical rename across ~9 node files) and over decorating each node at its own definition site (which spreads the tracing concern across every node file and risks the span name drifting out of sync with the name it's registered under in the graph). Wrapping at `add_node()` touches only the two files that already own graph wiring, costs one line per node, and reuses the registered name as the span name for free.

**Exception:** `pick_file_node` (`nodes/pick_file.py`) is sync (`def __call__`, not `async def`) and does no I/O — pure in-memory list slicing. It stays unwrapped; wrapping it would raise the (intentionally preserved) `TypeError` for sync callables, and there's nothing worth tracing inside it.

---

## Data Flow (after the fix)

Per query request:

```
HTTP span (FastAPI instrumentor — existing)
  node span (new — e.g. "memory_retrieval_node")
    httpx POST span (new — Ollama embedding call)
    asyncpg span (new — pgvector query)
  node span (new — e.g. "memory_persistence")
    SQLAlchemy span (new — fact/correction write)
  node span (new — e.g. "orchestrator", "rag_retrieval", "synthesis", ...)
    LLM/CHAIN spans (existing — ChatAnthropic via openinference-instrumentation-langchain)
psycopg span (new — checkpointer save/load, may appear at top level alongside node spans
  since AsyncPostgresSaver runs outside individual node bodies)
```

---

## Testing

Unit-level, matching existing conventions in `tests/unit/test_observability/test_tracing.py` and `tests/unit/test_graphs/`:

- `trace_node` accepts a class instance with async `__call__` (new test); still rejects a sync function (existing test, unaffected).
- `setup_tracing()` calls `.instrument()` once each on the 4 mocked instrumentor classes.
- Each graph builder test: build the graph with an in-memory span exporter active, invoke it, assert expected span names appear (and `pick_file` does not).

End-to-end confirmation is manual, not automated (needs live Phoenix/Ollama/Postgres): `just up-all`, send a real `/query` and `/ingest/file` request, inspect the trace waterfall at `localhost:6006` for the node spans and the nested `httpx`/`asyncpg`/SQLAlchemy/psycopg spans described above.

---

## Acceptance Criteria

1. `just lint`, `just format`, `just type-check` pass clean.
2. `just test-unit` passes, including new tests listed above.
3. After `just up-all`, a `/query` request shows named node spans nested under the HTTP span, each with the relevant driver-level child span(s) (httpx for embeddings, asyncpg for pgvector reads, SQLAlchemy for writes) inside it, visible in Phoenix's `second-brain` project.
4. An `/ingest/file` request shows an `ingest` span (and no `pick_file` span) with its own embedding/DB child spans.

---

## Files Changed

| Action | Path |
|--------|------|
| Modify | `apps/backend/pyproject.toml` |
| Modify | `apps/backend/uv.lock` |
| Modify | `apps/backend/src/second_brain/observability/tracing.py` |
| Modify | `apps/backend/src/second_brain/graphs/query_graph.py` |
| Modify | `apps/backend/src/second_brain/graphs/ingestion_graph.py` |
| Modify | `apps/backend/tests/unit/test_observability/test_tracing.py` |
| Modify | `apps/backend/tests/unit/test_graphs/test_query_graph_build.py` |
| Modify | `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py` |

---

## Out of Scope

- Custom span attributes (row counts, query text, embedding dimensions) — presence + timing only for now.
- Any change to `docs/codebase/001-tech-stack.md` beyond what's already there for the LangChain instrumentor — not updated here since no new user-facing tech choice is introduced, only additional instrumentation of tech already in use.
