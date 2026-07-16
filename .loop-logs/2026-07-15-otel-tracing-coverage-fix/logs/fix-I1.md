# Task I1 Log: Drop dead OTel provider reset in test_query_graph_build.py

## Task Context

### Plan Section
`apps/backend/tests/unit/test_graphs/test_query_graph_build.py`, in
`test_build_query_graph_wraps_nodes_in_spans`, manually saves/forces/restores OTel's
private `opentelemetry.trace._TRACER_PROVIDER` / `_TRACER_PROVIDER_SET_ONCE._done`
inline (both the setup before `trace.set_tracer_provider(provider)` and the `finally`
restore), with a comment claiming this test "lives outside" the directory that has an
autouse reset fixture. That comment is now FALSE: this same PR also added
`apps/backend/tests/unit/test_graphs/conftest.py`, an autouse fixture that performs the
identical save/restore for every test in this directory — including this one. The
manual block is dead weight with a misleading rationale. One reviewer verified
empirically (removed the block, ran the full suite, all 225 tests still passed).

The sibling test added in the same PR, `test_ingestion_graph.py::test_graph_emits_span_for_ingest_node_but_not_pick_file`,
does NOT do this manual reset — it just calls `trace.set_tracer_provider(provider)` and
relies on the fixture. Match that pattern.

### Acceptance Criteria
- AC-1: Remove the manual capture of the original provider/done-flag before
  `trace.set_tracer_provider(provider)`.
- AC-2: Remove the manual force-reset of `_TRACER_PROVIDER_SET_ONCE._done` (if present)
  before calling `set_tracer_provider`.
- AC-3: Remove the stale comment explaining why the manual reset exists.
- AC-4: Remove the manual restore in the `finally` block.
- AC-5: Keep the plain `trace.set_tracer_provider(provider)` call and the rest of the
  test unchanged.
- AC-6: `test_query_graph_build.py` tests all pass; full unit suite has no regression
  (225 passed, same count as before).
- AC-7: `just lint` and `just test-unit` exit 0.

---

## Attempt 1 — 2026-07-15T00:00:00Z

### Implementation Plan
- Remove the private-internal save (`original_provider`, `original_done`) and the
  forced reset of `_TRACER_PROVIDER` / `_TRACER_PROVIDER_SET_ONCE._done` before
  `trace.set_tracer_provider(provider)`, plus the stale comment justifying it.
- Convert the `try/finally` wrapping the `with patch(...)` block back into a plain
  `with` block (de-indent one level), dropping the `finally` restore of the private
  internals — the autouse `_reset_otel_tracer_provider` fixture in
  `test_graphs/conftest.py` now does this for every test in the directory.
- Drop the now-unused `import opentelemetry.trace as trace_api` (nothing else in the
  test references `trace_api` after the private-internal lines are removed).
- Run the target test file, then the full unit suite, then `just lint` and
  `just test-unit`.

### Files Changed
- modified `apps/backend/tests/unit/test_graphs/test_query_graph_build.py` — removed
  manual OTel `_TRACER_PROVIDER` / `_TRACER_PROVIDER_SET_ONCE._done` save/force/restore
  and stale comment in `test_build_query_graph_wraps_nodes_in_spans`; dropped unused
  `trace_api` import; de-indented the `with patch(...)` block after removing the
  wrapping `try/finally`.

### New Tests
(none — pure deletion of dead test-setup code, no new test coverage needed)

### Key Decisions
- Removed the `import opentelemetry.trace as trace_api` line even though the task
  instructions only listed the save/restore code for removal: after deleting the
  private-attribute lines, `trace_api` had no remaining references in the file, so
  keeping the import would fail `ruff` (F401 unused import) and violate the "lint must
  pass" gate.

### Lint Output
PASS
(`just lint` → "All checks passed!")

### Test Output
PASS (225 passed, 0 new)
- `uv run --package second-brain pytest apps/backend/tests/unit/test_graphs/test_query_graph_build.py -v` → 10 passed
- `uv run --package second-brain pytest apps/backend/tests/unit -v` → 225 passed, 2 warnings (pre-existing, unrelated deprecation warnings)
- `just test-unit` → 225 passed, 2 warnings

### Commit
`c3c2138`

### Outcome: success
