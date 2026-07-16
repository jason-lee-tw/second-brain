# Loop Summary

**Plan:** docs/superpowers/plans/2026-07-15-otel-tracing-coverage-fix.md
**Spec:** docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md
**Branch:** fix/000-otel-tracing-coverage
**Date:** 2026-07-16

## Tasks

| Task | Status | Attempts | Delivered |
|------|--------|----------|-----------|
| task-1-trace-node-callable-instances | completed | 1 | Let `trace_node()` wrap class-instance nodes |
| task-2-driver-level-instrumentation | completed | 1 | Add and wire up driver-level OTEL instrumentation |
| task-3-query-graph-node-spans | completed | 1 | Wrap every query-graph node in a span |
| task-4-ingestion-graph-node-span | completed | 1 | Wrap the ingestion-graph's async node in a span |
| task-5-full-verification-pass | delegated_to_stage2 | n/a | Full verification pass — no code changes; performed as Stage 2 VERIFY instead |

**Completed:** 4/4 implementation tasks
**Failed:** 0/4

Deviation from the plan's stated task sequencing: Task 3 and Task 4 explicitly consume
Task 1's fixed `trace_node()` (per their own Interfaces sections), so Stage 1 ran as two
dependency-respecting batches (Task 1 + Task 2 in parallel, squash-merged, then Task 3 +
Task 4 in parallel from the updated tip) rather than 4 fully-simultaneous worktrees.

## Verification

**Rounds:** 4 (see `.loop-logs/2026-07-15-otel-tracing-coverage-fix/tasks/verification-state.json`)

- Round 1: **fail** — SQLAlchemy write spans never emitted (`SQLAlchemyInstrumentor().instrument()` needs `engine=` to attach per-statement spans). Fixed in commit `90fdcde`.
- Round 2: **pass** — fix confirmed live via Phoenix trace inspection.
- Round 3: **pass** — re-verified after review-round-1 fixes (test cleanup, fixture hoist, doc corrections), no regressions.
- Round 4: **pass** — re-verified after review-round-2 fixes (functools.wraps state-leak fix, plan doc corrections), no regressions.

All 4 rounds included live system boot (`just up-all`), real `/query` and `/ingest/file`
requests, and Phoenix trace inspection via the `phoenix-trace-fetcher` skill — not just
unit tests.

## Review

**Loop iterations:** 3 of ≤5 (see `.loop-logs/2026-07-15-otel-tracing-coverage-fix/code-review/round-{1,2,3}.md`)

**Actionable issues found:** 6 (4 in round 1, 2 in round 2, 0 in round 3)
**Actionable issues fixed:** 5 (I1, I2, I4, R2-1, R2-2)
**Actionable issues resolved with no code change (false alarm, confirmed via live evidence):** 1 (I3 — psycopg checkpointer spans already worked correctly)

**Minor issues deferred (NOT handled yet):**
- M1: `observability/tracing.py` importing `db.session.engine` is a layering nit (generic module reaching into a business-domain module)
- M2: near-duplicate "sync, no I/O, not wrapped" comments across `query_graph.py`/`ingestion_graph.py`
- M3: no structural test enforcing every future node gets span-wrapped
- M4: vestigial try/finally `set_tracer_provider` restore in `test_ingestion_graph.py`
- M5: no structural guardrail against a future async node escaping `trace_node` wrapping (spec-acknowledged tradeoff)
- M6: span-capture test boilerplate duplicated across 4 test functions instead of hoisted
- M7: hand-rolled `base_state` dict in a test drifts from the `make_state()` factory (missing `context_used`)
- M8: span-name string literal retyped twice per `add_node()` call site (8 occurrences)
- M9: `is_async` guard theoretically may not generalize to `functools.partial`-wrapped instances (no such node exists today)
- M10: `trace_node`'s docstring/usage example doesn't mention the callable-instance form used by 8/8 production nodes
- M11: no test for the negative case of the widened contract (sync callable instance should still raise `TypeError`)
- M12: `DummyNode`/`StatefulDummyNode` test helpers are near-duplicates
- M13: `_reset_otel_tracer_provider` fixture is now autouse across all 226 tests instead of scoped to the 3 modules that need it
