# Task: task-1-apply-the-fix-tdd-red-green

## Plan Section

File: apps/backend/src/second_brain/graphs/query_graph.py, line ~49

Change: Add `kwargs={"autocommit": True}` to AsyncConnectionPool constructor.

## Acceptance Criteria

- AC-4: just format, just lint, just type-check, just test-unit all pass.
- New test `test_build_query_graph_pool_uses_autocommit` exists and passes.

---

## Attempt 1

**Status:** passed
**Lint:** exit 0
**Type-check:** exit 0
**Tests:** exit 0 (including test_build_query_graph_pool_uses_autocommit)
**Fix applied:** yes — added kwargs={"autocommit": True} to AsyncConnectionPool call

Committed: fix(query-graph): add autocommit=True to AsyncConnectionPool
