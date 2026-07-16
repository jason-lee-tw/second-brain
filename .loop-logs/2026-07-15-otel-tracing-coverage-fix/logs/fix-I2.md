# Task I2 Log: Hoist duplicated `_reset_otel_tracer_provider` fixture into shared conftest

## Task Context

### Finding (from 3 independent reviewers, converged)
`apps/backend/tests/unit/test_graphs/conftest.py` is a byte-for-byte duplicate of the
pre-existing `apps/backend/tests/unit/test_observability/conftest.py` (both define an
autouse `_reset_otel_tracer_provider` fixture that saves/restores OTel's private
`_TRACER_PROVIDER`/`_TRACER_PROVIDER_SET_ONCE._done`). A shared
`apps/backend/tests/unit/conftest.py` already exists (holds a `make_state` factory) —
it is the natural single home for a fixture needed by 2+ subdirectories, since pytest
conftest fixtures at a parent directory apply to all subdirectories.

### Acceptance Criteria
- AC-1: `_reset_otel_tracer_provider` autouse fixture lives in one place:
  `apps/backend/tests/unit/conftest.py`.
- AC-2: `apps/backend/tests/unit/test_graphs/conftest.py` and
  `apps/backend/tests/unit/test_observability/conftest.py` are deleted.
- AC-3: All 225 unit tests still pass, including the OTel-provider-swapping tests in
  both `test_graphs/` and `test_observability/`.
- AC-4: `just lint` exits 0.

---

## Attempt 1 — 2026-07-15T00:00:00Z

### Implementation Plan
- Read the existing shared `apps/backend/tests/unit/conftest.py` (`make_state` factory)
  and both duplicate conftest files to compare content.
- Move the `_reset_otel_tracer_provider` fixture (imports + fixture body) into the
  shared conftest, merging with `make_state` without deleting it.
- `git rm` both directory-level conftest files.
- Run `just test-unit` and `just lint` to verify.

### Files Changed
- modified `apps/backend/tests/unit/conftest.py` — added `_reset_otel_tracer_provider`
  autouse fixture (imports `opentelemetry.trace as trace_api`, `pytest`) alongside the
  pre-existing `make_state` factory.
- deleted `apps/backend/tests/unit/test_graphs/conftest.py` — fixture now inherited
  from parent conftest.
- deleted `apps/backend/tests/unit/test_observability/conftest.py` — fixture now
  inherited from parent conftest.

### New Tests
(none — this is a pure test-infrastructure de-duplication; no behavior change, existing
225 tests are the regression check.)

### Key Decisions
- The two duplicate files were near-identical, not byte-identical: `test_graphs/conftest.py`
  had a longer module docstring explicitly naming `test_ingestion_graph.py` as the
  reason the reset is needed and noting it "Mirrors the identical fixture in
  tests/unit/test_observability/conftest.py"; `test_observability/conftest.py` had a
  shorter, more generic docstring. The fixture body (assert + save/restore of
  `_TRACER_PROVIDER` / `_TRACER_PROVIDER_SET_ONCE._done`) was byte-identical in both.
  Kept the more detailed docstring as the canonical one, generalized to name all three
  known consumers (test_ingestion_graph.py, test_query_graph_build.py,
  test_tracing.py) and to explain why the fixture now lives at the parent-directory
  level instead of being duplicated per subdirectory.
- Placed the new fixture above `make_state` in the shared conftest (after the existing
  module docstring, before `make_state`) since fixtures conventionally precede
  factory functions in these files; no functional significance to the ordering.

### Lint Output
PASS (`just lint` → "All checks passed!")

### Test Output
PASS (225 passed, 0 new, 73.32s) — includes:
- `test_observability/test_tracing.py` (12 tests)
- `test_graphs/test_query_graph_build.py::test_build_query_graph_wraps_nodes_in_spans`
- `test_graphs/test_ingestion_graph.py::test_graph_emits_span_for_ingest_node_but_not_pick_file`
All passed with the fixture now sourced solely from the parent
`apps/backend/tests/unit/conftest.py` — confirms pytest fixture discovery correctly
applies the parent-level autouse fixture to both subdirectories with no naming
collisions or import errors.

### Commit
`5dacdb2`

### Outcome: success
