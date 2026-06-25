# Fix asyncpg JSONB Codec Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register a `jsonb` codec in the asyncpg pool init so the `metadata` JSONB column in `document_chunks` is automatically decoded to a Python dict, fixing the `ValueError` crash in `_row_to_chunk_metadata`.

**Architecture:** Extract a module-level `_setup_conn` coroutine that registers both the pgvector type codec and the jsonb codec. Pass it as `init=_setup_conn` to `asyncpg.create_pool`. No change to `_row_to_chunk_metadata` — the function already handles dicts correctly; the bug is upstream in the pool configuration.

**Tech Stack:** `asyncpg`, `pgvector.asyncpg.register_vector`, Python `json` stdlib (already available)

## Global Constraints

- All changes on branch `fix/resolve-query-issue` — never commit to `main`
- `just lint`, `just format`, `just type-check`, `just test-unit` must all pass before declaring done
- TDD: write failing test first, confirm red, then implement
- Conventional Commits enforced by `.hooks/commit-msg`
- Do NOT add new dependencies — `json` is stdlib, no `uv add` needed

---

## File Map

| Action | Path                                                       | Change                                                                                               |
| ------ | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Modify | `apps/backend/src/second_brain/nodes/rag_retrieval.py`     | Add `import json`; extract `_setup_conn`; pass as `init` to `create_pool`                            |
| Modify | `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py` | Add two tests: one for `_setup_conn` registering jsonb, one verifying pool passes `init=_setup_conn` |

---

## Task 1: Register JSONB codec in asyncpg pool (TDD)

**Files:**

- Modify: `apps/backend/src/second_brain/nodes/rag_retrieval.py:21-27`
- Test: `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py`

**Interfaces:**

- Produces: `_setup_conn(conn: asyncpg.Connection) -> None` — module-level coroutine, callable as `init` arg to `asyncpg.create_pool`

---

- [ ] **Step 1: Write the two failing tests**

Append to `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py` (after the existing `test_shutdown_rag_pool_closes_and_resets` test, before `test_query_pgvector_uses_pool_acquire`):

```python
import json as _json  # alias to avoid shadowing module-level `json` import


@pytest.mark.asyncio
async def test_setup_conn_registers_vector_and_jsonb_codec():
    """_setup_conn must call register_vector AND set_type_codec for jsonb."""
    from second_brain.nodes.rag_retrieval import _setup_conn

    mock_conn = AsyncMock()
    mock_conn.set_type_codec = AsyncMock()

    with patch(
        "second_brain.nodes.rag_retrieval.register_vector",
        new=AsyncMock(),
    ) as mock_rv:
        await _setup_conn(mock_conn)

    mock_rv.assert_awaited_once_with(mock_conn)
    mock_conn.set_type_codec.assert_awaited_once_with(
        "jsonb",
        encoder=_json.dumps,
        decoder=_json.loads,
        schema="pg_catalog",
    )


@pytest.mark.asyncio
async def test_get_rag_pool_passes_setup_conn_as_init():
    """asyncpg.create_pool must receive init=_setup_conn for JSONB auto-decoding."""
    from second_brain.nodes.rag_retrieval import _get_rag_pool, _setup_conn

    rag_retrieval._rag_pool = None
    mock_pool = AsyncMock()

    with patch(
        "second_brain.nodes.rag_retrieval.asyncpg.create_pool",
        new=AsyncMock(return_value=mock_pool),
    ) as mock_create:
        await _get_rag_pool("postgresql://test/db")

    mock_create.assert_awaited_once_with("postgresql://test/db", init=_setup_conn)

    # Clean up module-level state
    rag_retrieval._rag_pool = None
```

- [ ] **Step 2: Run tests to confirm they fail (red)**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_rag_retrieval.py::test_setup_conn_registers_vector_and_jsonb_codec tests/unit/test_nodes/test_rag_retrieval.py::test_get_rag_pool_passes_setup_conn_as_init -v
```

Expected: both FAIL — `ImportError: cannot import name '_setup_conn'` and `AssertionError` on init arg mismatch.

- [ ] **Step 3: Implement the fix**

In `apps/backend/src/second_brain/nodes/rag_retrieval.py`, make these changes:

**Add `import json` at the top** (after `import asyncio`, before `import asyncpg`):

```python
import json
```

**Replace the existing `_get_rag_pool` function** (lines 21-27) with:

```python
async def _setup_conn(conn: asyncpg.Connection) -> None:  # pyright: ignore[reportUnknownParameterType]
    """Pool init: register pgvector type codec and JSONB auto-decode for this connection."""
    await register_vector(conn)
    await conn.set_type_codec(  # pyright: ignore[reportUnknownMemberType]
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def _get_rag_pool(postgres_url: str) -> asyncpg.Pool:
    """Return the module-level connection pool, initialising it on first call."""
    global _rag_pool
    async with _rag_pool_lock:
        if _rag_pool is None:
            _rag_pool = await asyncpg.create_pool(postgres_url, init=_setup_conn)
    return _rag_pool
```

- [ ] **Step 4: Run the new tests to confirm they pass (green)**

```bash
cd apps/backend && python -m pytest tests/unit/test_nodes/test_rag_retrieval.py::test_setup_conn_registers_vector_and_jsonb_codec tests/unit/test_nodes/test_rag_retrieval.py::test_get_rag_pool_passes_setup_conn_as_init -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full test suite**

```bash
just format && just lint && just type-check && just test-unit
```

Expected: all pass, including all pre-existing `test_rag_retrieval.py` tests.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/nodes/rag_retrieval.py \
        apps/backend/tests/unit/test_nodes/test_rag_retrieval.py
git commit -m "fix(rag-retrieval): register jsonb codec in asyncpg pool init

asyncpg does not auto-decode JSONB columns to Python dicts; it returns
raw JSON strings. _row_to_chunk_metadata called dict() on the string,
which iterates characters and raises ValueError.

Extract _setup_conn to register both register_vector and a jsonb codec
so every connection in the pool auto-decodes JSONB to Python dicts."
```

---

## Task 2: Verify end-to-end on the running system

- [ ] **Step 1: Rebuild and restart the backend container**

```bash
just up-all
```

Wait for the backend to be healthy (watch logs until you see `Application startup complete`):

```bash
docker logs $(docker ps -qf "name=backend") -f --tail 20
```

- [ ] **Step 2: Hit `POST /query` and confirm 200**

```bash
curl -s -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What is in my second brain?"}' | python3 -m json.tool
```

Expected: HTTP 200, response body contains `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext`. No `ValueError` in backend logs.

- [ ] **Step 3: Confirm no ValueError in backend logs**

```bash
docker logs $(docker ps -qf "name=backend") --tail 30 2>&1 | grep -i "error\|exception\|traceback" || echo "No errors found"
```

Expected: output is `No errors found` (or only unrelated startup noise).

---

## Done Checklist

- [ ] `just format` passes with no changes
- [ ] `just lint` passes with no findings
- [ ] `just type-check` passes without error or warning
- [ ] `just test-unit` passes (including `test_setup_conn_registers_vector_and_jsonb_codec` and `test_get_rag_pool_passes_setup_conn_as_init`)
- [ ] `POST /query` returns 200 on the running system
- [ ] No `ValueError` in backend logs after the query
