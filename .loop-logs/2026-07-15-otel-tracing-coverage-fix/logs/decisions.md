# Decisions & Challenges — 2026-07-15-otel-tracing-coverage-fix

## task-1-trace-node-callable-instances

### Key decisions
- Widened `trace_node`'s guard to `inspect.iscoroutinefunction(func) or inspect.iscoroutinefunction(getattr(func, "__call__", None))`, exactly as specified in the plan — no deviation.

## task-2-driver-level-instrumentation

### Key decisions
- Added the 4 `opentelemetry-instrumentation-*` deps via `uv add`; verified diff was purely additive. No deviation from the plan.

## task-3-query-graph-node-spans

### Key decisions
- **Did not wrap `redact_inbound`/`redact_outbound` in `trace_node`**, deviating from the plan's Task 3 literal instructions. Diagnosis showed both are genuinely sync (`def __call__`, pure regex PII redaction, no I/O) — `trace_node` only accepts async callables. Wrapping them as literally instructed broke 4 pre-existing tests and would crash `build_query_graph()` in production. This mirrors Task 4's own established precedent for `pick_file_node`. Judged a genuine gap in the plan text (it didn't account for the PII nodes being sync), not a convenience deviation. Orchestrator verified this independently by reading `pii_redaction.py` before accepting the deviation.
- Rewrote the plan's literal test (which called `graph.ainvoke()` against a mocked `AsyncPostgresSaver` and crashed with cascading `TypeError`s from LangGraph's Pregel checkpoint loop) to invoke each node directly via `graph.nodes[name].ainvoke(state)` instead — narrower, bypasses the checkpoint loop, verified empirically before committing.

### Challenges faced
- Attempt 1 succeeded, but only after diagnosing why the literal plan test crashed (mocked checkpointer incompatible with LangGraph's Pregel executor) and why wrapping all 9 nodes broke 4 existing tests (2 nodes are sync).

## task-4-ingestion-graph-node-span

### Key decisions
- The plan's literal test manually swaps OTel's global `TracerProvider` via the public API and restores it in `finally` — but OTel's `Once` guard makes the "restore" silently a no-op, permanently tripping the latch for every subsequent test in the same pytest session. This broke 5 pre-existing tests in `test_observability/test_tracing.py` when running the full suite (invisible when running the new test file alone). Fixed by adding an autouse `_reset_otel_tracer_provider` fixture (mirroring the existing one in `test_observability/conftest.py`, which is scoped only to its own directory) in a new `test_graphs/conftest.py` — scoped minimally to avoid colliding with the parallel task-3 worktree.

### Challenges faced
- Attempt 1 succeeded, but only after root-causing a full-suite-only failure (5 tests) that didn't reproduce when running the new test file in isolation.

## Verification round 1

### Root cause found
- `SQLAlchemyInstrumentor().instrument()` called with no arguments only patches `create_engine`/`Engine.connect` at the class level — it never attaches the per-statement `EngineTracer` to an engine that already exists (confirmed by reading the installed library source). `db/session.py`'s `engine` is a module-level singleton constructed before `setup_tracing()` runs, so SQLAlchemy write spans (for `learned_facts`/`document_chunks`/`ingested_documents`) never appeared, even though the writes succeeded. Fixed with `SQLAlchemyInstrumentor().instrument(engine=engine)`, importing `engine` from `second_brain.db.session`. Verified live via Phoenix trace inspection in round 2 (real `INSERT` spans with `db.statement` text now appear).

## Review round 1 fixes

- **I1** (fixed): removed a manual OTel `TracerProvider` reset in `test_query_graph_build.py`'s new test, made fully redundant by `test_graphs/conftest.py`'s autouse fixture (added in task-4) — the removal comment had gone stale once that fixture existed.
- **I2** (fixed): hoisted the duplicated `_reset_otel_tracer_provider` fixture (present near-identically in both `test_graphs/conftest.py` and `test_observability/conftest.py`) into the shared `tests/unit/conftest.py`; deleted both directory-level copies.
- **I3** (no_change_needed): a reviewer flagged that psycopg checkpointer spans were never independently confirmed live, given the identical silent-no-op failure mode had just been found for SQLAlchemy. Live investigation found `PsycopgInstrumentor()`'s bare `.instrument()` call patches `AsyncConnection.connect` at the class level — looked up fresh on every call, unlike SQLAlchemy's one-shot `create_engine` factory wrap — so it correctly instruments connections opened later by `AsyncConnectionPool`, regardless of construction order. Confirmed via live Phoenix trace showing checkpoint-table spans as siblings of the node spans, as the spec predicted. Root cause: different instrumentors patch at genuinely different points; the SQLAlchemy failure mode doesn't generalize to psycopg.
- **I4** (fixed, later found incomplete): corrected two false claims in the spec ("call each instrumentor with no arguments" — wrong for SQLAlchemy; PyPI version `0.64b0` — actual `0.63b1`) and added an "Implementation Notes" section documenting the `redact_inbound`/`redact_outbound` exclusion. The fix only touched the spec file, not the plan file also named in the finding's own evidence — surfaced as R2-2 in round 2.

## Review round 2 fixes

- **R2-1** (fixed): `functools.wraps(func)` in `trace_node`'s decorator unconditionally merges a wrapped callable instance's `__dict__` onto the returned wrapper function (`WRAPPER_UPDATES = ('__dict__',)` has no guard, unlike the name/qualname assignments which skip missing attributes). For stateful `BaseAgentNode` instances, this leaked internal attributes (e.g. `self._agent`) onto the wrapper — verified empirically. Inert today (nothing reads these off the wrapper) but a real defeat of encapsulation. Fixed with `functools.wraps(func, updated=())`; added a regression test using a stateful dummy node (the existing test helper had no `__init__` state, which is exactly why the leak went unnoticed).
- **R2-2** (fixed): applied the same correction as I4 to the plan file, which had been missed — added 3 additive "Post-delivery correction" blockquotes next to the stale SQLAlchemy snippet and the `redact_inbound`/`redact_outbound` references, rather than silently rewriting the plan's original text.

## Review round 3

No actionable (blocking/important) issues found by any of 3 independent reviewers — loop exited per Loop Control (actionable count == 0). 13 minor issues remain deferred across all 3 rounds (see summary.md).
