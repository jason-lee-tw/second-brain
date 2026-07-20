# Task 11 Log: Register Router in `main.py`

## Task Context

### Plan Section
### Task 11: Register Router in `main.py`

**Files:**
- Modify: `apps/backend/src/second_brain/main.py`

- [ ] **Step 1: Write a test that the `/query` route exists on the app**

```python
# apps/backend/tests/unit/test_app_routes.py
from fastapi.testclient import TestClient
from second_brain.main import app


def test_query_route_registered():
    """Verify /query is registered — a POST with no body returns 422, not 404."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/query", json={})
    # 422 = validation error (missing 'message' field) = route exists
    # 404 = route not registered
    assert response.status_code != 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_app_routes.py::test_query_route_registered -v
```

Expected: FAIL — response is 404 because the router is not yet registered.

- [ ] **Step 3: Register the router in `main.py`**

Open `apps/backend/src/second_brain/main.py`. Find the block where other routers are included (look for `app.include_router(...)` calls). Add the following import and registration:

```python
# In apps/backend/src/second_brain/main.py
# Add this import alongside existing router imports:
from second_brain.api.routers.query import router as query_router

# Add this alongside existing include_router calls:
app.include_router(query_router)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/backend && pytest tests/unit/test_app_routes.py::test_query_route_registered -v
```

Expected: 1 test PASS (status code 422, not 404).

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/main.py \
  tests/unit/test_app_routes.py
git commit -m "feat(main): register /query router in FastAPI app"
```

> **Note (deviation from plan, per task dispatch instructions):** This repo already has
> `apps/backend/tests/unit/test_main.py` covering app-level wiring (lifespan teardown).
> The dispatch instructions require appending the route-registration test there instead
> of creating a new flat `test_app_routes.py`, and using
> `TestClient(app, raise_server_exceptions=False)` with an empty JSON body per the plan's
> test intent.
</content>

## Attempt 1 — 2026-07-20T05:27:37Z

### Implementation Plan
- Append a route-registration test to the existing `apps/backend/tests/unit/test_main.py` (not a new `test_app_routes.py`), asserting `POST /query` with an empty JSON body returns non-404
- Run `just test-unit` to confirm the new test fails with 404 (router not yet registered)
- Import `query` module and `query_router` in `main.py`; add `app.include_router(query_router)`; add a fourth lifespan teardown block calling `await query.shutdown()`
- Run `just lint` and `just test-unit` to confirm both pass

### Files Changed
- modified `apps/backend/tests/unit/test_main.py` — added `test_query_route_registered`, imported `TestClient`
- modified `apps/backend/src/second_brain/main.py` — imported `query` module + `query_router`, registered `/query` router, added `query.shutdown()` teardown block in `lifespan`

### New Tests
- `test_query_route_registered`

### Key Decisions
- Imported both the `query` module (for `query.shutdown()`) and `query_router` name (for `include_router`) rather than aliasing a single import, to mirror the existing `from second_brain.nodes import ingestion_agent` module-import pattern used for the other teardown call while keeping `include_router` call symmetrical with `ingest_router`.

### Lint Output
PASS

### Test Output
PASS (131 passed, 1 new)

### Commit
`124d3dd`

### Outcome: success
