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

## Task 1: Apply the fix

**File:** `apps/backend/src/second_brain/graphs/query_graph.py`, line 49

- [ ] **Step 1: Apply the one-line fix**

```python
# BEFORE (line 49)
pool = AsyncConnectionPool(conninfo=postgres_url, open=False)

# AFTER
pool = AsyncConnectionPool(conninfo=postgres_url, open=False, kwargs={"autocommit": True})
```

- [ ] **Step 2: Run lint and type-check**

```bash
just lint && just type-check
```

Expected: no errors.

- [ ] **Step 3: Run unit tests**

```bash
just test-unit
```

Expected: all unit tests PASS (no regressions).

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

- [ ] `just lint` passes
- [ ] `just type-check` passes
- [ ] `just test-unit` passes
- [ ] `POST /query` returns 200 on the running system
- [ ] Session continuity confirmed (second call with same `sessionId` returns 200)
