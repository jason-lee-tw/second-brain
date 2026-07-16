# Task I3 Log: Verify psycopg checkpointer span presence in live Phoenix trace

## Task Context

### Finding (verbatim from dispatch)
A reviewer flagged that the psycopg checkpointer span (LangGraph's `AsyncPostgresSaver`
via `psycopg_pool.AsyncConnectionPool`, wired up in
`apps/backend/src/second_brain/graphs/query_graph.py`) was never independently
confirmed present in a live Phoenix trace, across two prior verification rounds.
`apps/backend/src/second_brain/observability/tracing.py:56` calls
`PsycopgInstrumentor().instrument()` with no arguments. Earlier in this same PR, an
identical bare `.instrument()` call for SQLAlchemy silently produced ZERO
per-statement spans because the target engine was a module-level singleton
constructed before `setup_tracing()` ran — the instrumentor patched the wrong hook
(class-level `create_engine`/`Engine.connect`, not the already-existing instance).
This finding exists because that failure mode might repeat here and nobody has
actually looked.

Mitigating factor already reasoned about (but NOT verified): the psycopg
`AsyncConnectionPool` in `query_graph.py` is constructed lazily per-process (inside
`build_query_graph()`, called from `api/routers/query.py`'s request-scoped graph
getter), which plausibly runs AFTER `setup_tracing()` already executed in the FastAPI
lifespan — unlike `db/session.py`'s eager module-level `engine`.

### Acceptance Criteria
- AC-1: Read the psycopg instrumentor source and query_graph/main.py wiring to form
  a hypothesis for whether the bare `.instrument()` call actually works for the
  checkpointer's connections.
- AC-2: Boot the stack, send a real `/query` request that exercises the checkpointer,
  and fetch the resulting trace from Phoenix.
- AC-3: Confirm (or refute) presence of a psycopg-attributed span with concrete
  trace/span-id evidence — not re-reading code.
- AC-4: If missing, root-cause and apply the minimal fix in `tracing.py` (following
  the SQLAlchemy fix pattern from commit `90fdcde`), add a unit test, verify lint +
  unit tests, and re-verify live. If present, make no code changes.

## Attempt 1 — 2026-07-15T00:00:00Z (approximate, single pass — no retries needed)

### Investigation / Hypothesis

Read:
- `apps/backend/src/second_brain/graphs/query_graph.py` — `AsyncConnectionPool` and
  `AsyncPostgresSaver` are constructed inside `build_query_graph()`, an async
  function with no module-level instantiation.
- `apps/backend/src/second_brain/api/routers/query.py` — `build_query_graph()` is
  only called from `_get_graph()`, which is invoked lazily on the first `/query`
  request (guarded by `asyncio.Lock`), i.e. strictly after the FastAPI lifespan
  (and therefore `setup_tracing()`) has already run. There is no module-level
  singleton analogous to `db/session.py`'s eager `engine`.
- `apps/backend/src/second_brain/main.py` — `setup_tracing()` runs synchronously
  at the top of `lifespan()`, before the app starts serving requests.
- `apps/backend/src/second_brain/observability/tracing.py:55` — bare
  `PsycopgInstrumentor().instrument()`.
- Installed library source:
  `.venv/lib/python3.13/site-packages/opentelemetry/instrumentation/psycopg/__init__.py`
  — `_instrument()` calls `dbapi.wrap_connect(...)` three times, patching
  `psycopg.connect`, `psycopg.Connection.connect`, and `psycopg.AsyncConnection.connect`
  **as class-level methods**, looked up dynamically on every call — not a one-shot
  factory-function wrap like SQLAlchemy's `create_engine()`.
- `.venv/lib/python3.13/site-packages/psycopg_pool/pool_async.py:692` —
  `AsyncConnectionPool._connect()` creates each physical connection via
  `await self.connection_class.connect(conninfo, **kwargs)`.
- `.venv/lib/python3.13/site-packages/psycopg_pool/_compat.py` — `AsyncPoolConnection`
  (the pool's default `connection_class` on psycopg < 3.3) subclasses
  `psycopg.AsyncConnection` and only overrides `close()`, not `connect()` — so it
  inherits the patched `connect` classmethod via normal MRO lookup.

**Hypothesis:** unlike SQLAlchemy (where the bare call patches a factory function
that had already fired before `setup_tracing()` ran, producing zero spans), the
psycopg case should work correctly even with a bare `.instrument()` call — because
(a) the pool object is constructed lazily, well after `setup_tracing()`, and
(b) even if it weren't, the actual physical `connect()` call happens lazily every
time the pool opens a new connection, and that call is dispatched dynamically
through the patched class attribute — not captured early. This is a materially
different patch shape than SQLAlchemy's, so the earlier failure mode should not
repeat here.

### Live Verification

1. `just up-all` — booted Ollama + full Docker Compose stack (backend on
   `localhost:3001`, Phoenix on `localhost:6006`). Waited for `GET /health` to
   return 200.
2. Sent:
   ```
   curl -s -X POST http://localhost:3001/query -H "Content-Type: application/json" \
     -d '{"message": "hello", "session_id": "verify-psycopg-1"}'
   ```
   Response: `200`, `sessionId: 019f64cb-6d90-7e5e-890d-ab0caa1e0c10`, non-empty
   `answer`.
3. Fetched the most recent trace in the `second-brain` Phoenix project via the
   `phoenix-trace-fetcher` skill (`fetch_trace.py`, project override
   `PHOENIX_PROJECT=second-brain`):
   - **Trace ID:** `eddaef63da1259fe3984f525cf40d645` (62 spans, 8388ms total)
   - Root span `POST /query` (`span_id=b39d7f5fe3a94426`) has two sibling
     subtrees: the `LangGraph` chain span (containing the `trace_node`-wrapped
     node spans: `redact_inbound`, `memory_retrieval_node`, `orchestrator`,
     `synthesis`, `redact_outbound`, `memory_agent`, `memory_persistence`), and a
     flat run of `CREATE` / `SELECT` / `select` / `INSERT` spans that are direct
     children of the root — exactly the "sibling of the node spans, not nested
     inside one" shape predicted by the spec's own reasoning, since the
     checkpointer runs as part of LangGraph's state-persistence machinery around
     node execution, not inside a single node.
4. Pulled full attributes for representative spans via the Phoenix REST client
   (`client.spans.get_spans`):

   **Span `49ee5fa0d6bf4f9e`** (name `CREATE`, parent `b39d7f5fe3a94426` = root):
   ```
   db.name = second_brain
   db.user = second_brain
   db.system = postgresql
   db.statement = CREATE TABLE IF NOT EXISTS checkpoint_migrations (
       v INTEGER PRIMARY KEY
   );
   net.peer.name = app_postgres
   net.peer.port = 5432
   ```
   This is `AsyncPostgresSaver.setup()`'s own migration-table DDL — a statement
   only the psycopg-based checkpointer ever issues (nothing else in this
   codebase creates `checkpoint_migrations`).

   Additional sibling spans (`SELECT v FROM checkpoint_migrations`, dozens of
   `INSERT INTO checkpoints`, `INSERT INTO checkpoint_blobs`,
   `INSERT INTO checkpoint_writes`, and a `select ... from checkpoints WHERE
   thread_id = %s ...` read-back query) all carry the same
   `db.system=postgresql`, `net.peer.name=app_postgres`, `net.peer.port=5432`
   attribute shape — the exact SQL vocabulary of `langgraph.checkpoint.postgres`'s
   `AsyncPostgresSaver`, and psycopg's `%s` paramstyle (not asyncpg's `$1` style).

   **Contrast — asyncpg spans for comparison** (nested under
   `memory_retrieval_node`, span `3fa352acb9ed0b1b`):
   ```
   SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score
     FROM learned_facts WHERE (embedding<=>$1) < $2 ...
   db.system = postgresql
   net.peer.name = app_postgres
   net.peer.port = 5432
   net.transport = ip_tcp        <-- present only on asyncpg spans
   ```
   These use `$1`/`$2` paramstyle (asyncpg) and carry `net.transport`, which the
   psycopg instrumentor's `_CONNECTION_ATTRIBUTES` mapping does not set — a clean
   attribute-level distinguisher confirming the checkpoint spans are a genuinely
   separate instrumentor (psycopg), not asyncpg spans mislabeled.

5. `just down-all` — stack torn down cleanly (Ollama, backend, phoenix,
   app_postgres, phoenix_postgres, both networks all removed).

### Root Cause Analysis (why psycopg differs from the SQLAlchemy case)

The SQLAlchemy bug (fixed in commit `90fdcde`) occurred because
`SQLAlchemyInstrumentor().instrument()` without `engine=` only wraps the
`create_engine()` **factory function** — a one-shot call that had already
executed (producing the module-level `engine` singleton in `db/session.py`)
before `setup_tracing()` ran in the lifespan. Patching the factory after the
instance already exists is a no-op for that instance.

`PsycopgInstrumentor().instrument()` patches `psycopg.AsyncConnection.connect`
itself as a class attribute, looked up fresh on every call — not a factory
function invoked once at startup. Two independent facts make this safe here:
(1) `AsyncConnectionPool` in `query_graph.py` is built request-scoped/lazily
(no eager module-level singleton exists for psycopg, unlike SQLAlchemy's
`engine`), and (2) even disregarding (1), `pool_async.py`'s `_connect()` calls
`self.connection_class.connect(...)` fresh every time the pool needs a new
physical connection — so the patched `connect` is what actually executes,
regardless of when the pool object was constructed relative to
`setup_tracing()`.

### Decision

**No psycopg span is missing.** The finding's concern (repeat of the SQLAlchemy
failure mode) does not apply to psycopg's instrumentation strategy. Verified with
concrete trace/span evidence above, not by re-reading code.

### Files Changed
(none)

### New Tests
(none — no_change_needed)

### Lint Output
n/a — no code changed

### Test Output
n/a — no code changed

### Commit
n/a — no_change_needed, nothing to commit

### Outcome: success (no_change_needed)
