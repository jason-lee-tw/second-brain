# Task verification-fix-1 Log: SQLAlchemy write spans never appear (engine not attached)

## Task Context

### Plan Section
(No separate plan/spec file scopes this fix — it is a verification-round fix found by
booting the full stack and inspecting live Phoenix traces. Requirement being restored:
`docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md` AC3/AC4.)

**Bug description (from live verification run):**

A verifier booted the full stack (`just up-all`), sent real `/query` and `/ingest/file`
requests, and inspected the resulting traces in Phoenix. Named LangGraph node spans and
httpx/asyncpg child spans all work correctly. But SQLAlchemy write spans NEVER appear,
even though the DB writes succeed (confirmed by querying Postgres directly — rows exist
with timestamps inside the trace window).

Root cause (confirmed by reading the installed library source,
`opentelemetry/instrumentation/sqlalchemy/__init__.py` lines 161-294, function
`SQLAlchemyInstrumentor._instrument`): a bare `SQLAlchemyInstrumentor().instrument()`
call with no arguments only patches the `create_engine` factory functions and
`Engine.connect` at the class level. It does NOT attach an `EngineTracer` (the object
that hooks `before_cursor_execute`/`after_cursor_execute` to emit per-statement
SELECT/INSERT spans) unless you pass `engine=<instance>` or `engines=<list>` explicitly.
`apps/backend/src/second_brain/db/session.py` constructs its engine at import time as a
module-level singleton (`engine = create_engine(settings.database_url, echo=False)`), so
even the wrapped-factory path never applies to it (it's already constructed before
`setup_tracing()` runs inside the FastAPI lifespan).

**Fix:** in `apps/backend/src/second_brain/observability/tracing.py`, import the module-
level `engine` from `second_brain.db.session` and change
`SQLAlchemyInstrumentor().instrument()` to `SQLAlchemyInstrumentor().instrument(engine=engine)`.

### Acceptance Criteria
- AC-1 (restoring spec AC3): after `just up-all`, a `/query` request shows named node
  spans nested under the HTTP span, each with the relevant driver-level child span(s)
  (httpx for embeddings, asyncpg for pgvector reads, SQLAlchemy for writes) inside it,
  visible in Phoenix's `second-brain` project.
- AC-2 (restoring spec AC4): an `/ingest/file` request shows an `ingest` span (and no
  `pick_file` span) with its own embedding/DB child spans — including SQLAlchemy write
  spans.
- AC-3 (regression test): `test_instruments_raw_drivers` must fail against the
  pre-fix code (asserting `instrument()` called with no args passes even with the bug)
  and pass only when `SQLAlchemyInstrumentor().instrument` is asserted called with
  `engine=<the actual db.session.engine object>`.

## Attempt 1 — 2026-07-15T07:35:03Z

### Implementation Plan
- Update `test_instruments_raw_drivers` to assert `SQLAlchemyInstrumentor().instrument`
  is called with `engine=db_engine` (imported from `second_brain.db.session`), and
  confirm it fails against the current (buggy) code first.
- Add `from second_brain.db.session import engine` to `tracing.py` and change
  `SQLAlchemyInstrumentor().instrument()` to `.instrument(engine=engine)`.
- Check for circular imports: `second_brain.db.session` only imports
  `second_brain.config`, which has no internal `second_brain.*` deps — no cycle.
- Re-run the full tracing test file, then `just lint` and `just test-unit`.

### Files Changed
- modified `apps/backend/src/second_brain/observability/tracing.py` — import the
  module-level `engine` singleton from `db/session.py` and pass it explicitly to
  `SQLAlchemyInstrumentor().instrument(engine=engine)` so an `EngineTracer` is
  actually attached (bare `.instrument()` only patches `create_engine`/`Engine.connect`
  at the class level, which never applies to an engine already constructed at import
  time).
- modified `apps/backend/tests/unit/test_observability/test_tracing.py` — import
  `second_brain.db.session.engine` as `db_engine` and assert
  `mock_sqlalchemy.return_value.instrument.assert_called_once_with(engine=db_engine)`
  instead of the no-args assertion that passed even with the bug present.

### New Tests
(none — regression coverage added by strengthening the existing
`test_instruments_raw_drivers` assertion, no new test function)

### Key Decisions
- Confirmed the strengthened assertion fails against the pre-fix code first (`instrument()`
  called with no args vs. expected `engine=db_engine`) before applying the fix, per TDD.
- No deferred/local import needed inside `setup_tracing()` — `db.session`'s only
  internal dependency is `second_brain.config`, which has zero `second_brain.*` imports,
  so importing `engine` at module level in `tracing.py` introduces no cycle.

### Lint Output
PASS

### Test Output
PASS (225 passed, 0 new test functions — 1 existing test strengthened)

### Commit
`d4e73f5`

### Outcome: success
