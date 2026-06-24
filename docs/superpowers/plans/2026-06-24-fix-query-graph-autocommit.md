# Fix Plan: AsyncConnectionPool autocommit

**Date:** 2026-06-24  
**Spec:** `docs/superpowers/specs/2026-06-24-query-graph-autocommit-fix.md`  
**Bug:** `docs/bugs/2026-06-24-query-graph-autocommit.md`

---

## File Map

| Action | Path | Change |
|--------|------|--------|
| Modify | `apps/backend/src/second_brain/graphs/query_graph.py` | Add `kwargs={"autocommit": True}` to pool constructor |

---

## Task 1: Apply the fix (TDD — red → green)

**File:** `apps/backend/src/second_brain/graphs/query_graph.py`, line 49

- [ ] **Step 1: Write the failing test (red)**

Add to `apps/backend/tests/unit/test_graphs/test_query_graph_build.py`:

```python
@pytest.mark.asyncio
async def test_build_query_graph_pool_uses_autocommit():
    """AsyncConnectionPool must be constructed with autocommit=True for LangGraph DDL."""
    mock_pool = AsyncMock()
    mock_pool_class = MagicMock(return_value=mock_pool)
    mock_saver = MagicMock()
    mock_saver.setup = AsyncMock()

    with (
        patch("second_brain.graphs.query_graph.AsyncConnectionPool", mock_pool_class),
        patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
    ):
        MockSaver.return_value = mock_saver
        from second_brain.graphs.query_graph import build_query_graph

        await build_query_graph("postgresql://fake:fake@localhost:5432/test")

    mock_pool_class.assert_called_once_with(
        conninfo="postgresql://fake:fake@localhost:5432/test",
        open=False,
        kwargs={"autocommit": True},
    )
```

- [ ] **Step 2: Confirm the test fails (red)**

```bash
just test-unit
```

Expected: `test_build_query_graph_pool_uses_autocommit` FAILS — the pool is constructed without `kwargs`.

- [ ] **Step 3: Apply the one-line fix (green)**

```python
# BEFORE (line 49)
pool = AsyncConnectionPool(conninfo=postgres_url, open=False)

# AFTER
pool = AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})
```

- [ ] **Step 4: Run format, lint, type-check, and unit tests**

```bash
just format && just lint && just type-check && just test-unit
```

Expected: all pass, including `test_build_query_graph_pool_uses_autocommit`.

---

## Task 2: Verify end-to-end on the running system

- [ ] **Step 1: Rebuild and restart the backend container**

```bash
just up-all
```

- [ ] **Step 2: Hit `POST /query` and confirm 200**

```bash
curl -s -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What is in my second brain?"}' | jq .
```

Expected: HTTP 200, response body contains `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`.

- [ ] **Step 3: Confirm session continuity (AC-3)**

Use the `sessionId` from Step 2:

```bash
curl -s -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me more.", "session_id": "<sessionId from step 2>"}' | jq .
```

Expected: HTTP 200, same `sessionId` returned.

---

## Done Checklist

- [ ] `just format` passes
- [ ] `just lint` passes
- [ ] `just type-check` passes
- [ ] `just test-unit` passes (including `test_build_query_graph_pool_uses_autocommit`)
- [ ] `POST /query` returns 200 on the running system
- [ ] Session continuity confirmed (second call with same `sessionId` returns 200)
