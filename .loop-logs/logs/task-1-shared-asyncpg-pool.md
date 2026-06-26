# Task 1 Log: Shared asyncpg Pool (db/pool.py) + Migrate rag_retrieval.py

## Task Context

### Plan Section
### Task 1: Shared asyncpg Pool (`db/pool.py`) + Migrate `rag_retrieval.py`

**Files:**

- Create: `apps/backend/src/second_brain/db/pool.py`
- Modify: `apps/backend/src/second_brain/nodes/rag_retrieval.py`
- Test: `apps/backend/tests/unit/test_db/test_pool.py`

**Interfaces:**

- Produces: `get_pgvector_pool() -> asyncpg.Pool`, `shutdown_pgvector_pool() -> None`
- Consumed by: `memory_retrieval_node` (Task 3), `memory_persistence_node` (Task 6)

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_db/test_pool.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_pgvector_pool_initialises_once():
    """Calling get_pgvector_pool() twice returns the same pool — only created once."""
    import second_brain.db.pool as pool_module

    saved = pool_module._pgvector_pool
    pool_module._pgvector_pool = None  # reset singleton for test isolation

    mock_pool = MagicMock()
    with patch("second_brain.db.pool.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        p1 = await pool_module.get_pgvector_pool()
        p2 = await pool_module.get_pgvector_pool()

    pool_module._pgvector_pool = saved  # restore

    assert p1 is p2
    assert p1 is mock_pool


@pytest.mark.asyncio
async def test_shutdown_pgvector_pool_closes_and_resets():
    """shutdown_pgvector_pool() closes the pool and sets the singleton to None."""
    import second_brain.db.pool as pool_module

    mock_pool = AsyncMock()
    pool_module._pgvector_pool = mock_pool

    await pool_module.shutdown_pgvector_pool()

    mock_pool.close.assert_awaited_once()
    assert pool_module._pgvector_pool is None


@pytest.mark.asyncio
async def test_shutdown_noop_when_pool_is_none():
    """shutdown_pgvector_pool() does nothing if the pool was never initialised."""
    import second_brain.db.pool as pool_module

    saved = pool_module._pgvector_pool
    pool_module._pgvector_pool = None

    await pool_module.shutdown_pgvector_pool()  # must not raise

    pool_module._pgvector_pool = saved
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && python -m pytest tests/unit/test_db/test_pool.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.db.pool'`

- [ ] **Step 3: Create `db/pool.py`**

First create the `test_db` package directory:

```bash
mkdir -p apps/backend/tests/unit/test_db && touch apps/backend/tests/unit/test_db/__init__.py
```

Then create the pool module:

```python
# apps/backend/src/second_brain/db/pool.py
"""Shared asyncpg connection pool for pgvector queries.

Both rag_retrieval and memory_retrieval_node call get_pgvector_pool().
"""
import asyncio
import json

import asyncpg
from pgvector.asyncpg import register_vector

from second_brain.config import settings

_pgvector_pool: asyncpg.Pool | None = None
_pgvector_pool_lock: asyncio.Lock = asyncio.Lock()


async def _setup_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )


async def get_pgvector_pool() -> asyncpg.Pool:
    global _pgvector_pool
    async with _pgvector_pool_lock:
        if _pgvector_pool is None:
            _pgvector_pool = await asyncpg.create_pool(  # type: ignore[assignment]
                settings.postgres_url, init=_setup_conn
            )
    return _pgvector_pool  # type: ignore[return-value]


async def shutdown_pgvector_pool() -> None:
    global _pgvector_pool
    if _pgvector_pool is not None:
        await _pgvector_pool.close()
        _pgvector_pool = None
```

- [ ] **Step 4: Migrate `rag_retrieval.py` to import from `db/pool.py`**

Open `apps/backend/src/second_brain/nodes/rag_retrieval.py`.

Remove these module-level symbols (they are being moved to `db/pool.py`):

- `_rag_pool: asyncpg.Pool | None = None`
- `_rag_pool_lock: asyncio.Lock = asyncio.Lock()`
- `async def _setup_conn(conn: asyncpg.Connection) -> None: ...`
- `async def _get_rag_pool(postgres_url: str) -> asyncpg.Pool: ...`
- `async def shutdown_rag_pool() -> None: ...`

Add this import:

```python
from second_brain.db.pool import get_pgvector_pool
```

Update `_query_pgvector` to drop the `postgres_url` parameter and call `get_pgvector_pool()`:

```python
async def _query_pgvector(embedding: list[float], top_k: int = 5) -> list[RagResult]:
    """Query the document_chunks table for the top-k most similar chunks."""
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT content, 1-(embedding<=>$1) AS score, chunk_index, metadata"
            " FROM document_chunks"
            " ORDER BY embedding<=>$1"
            " LIMIT $2",
            embedding,
            top_k,
        )
        return [
            {
                "content": r["content"],
                "score": float(r["score"]),  # pyright: ignore[reportUnknownArgumentType]
                "chunk_index": r["chunk_index"],
                "metadata": (
                    _row_to_chunk_metadata(r["metadata"])  # pyright: ignore[reportUnknownArgumentType]
                    if r["metadata"]
                    else None
                ),
            }
            for r in rows
        ]
```

Update `retrieve_from_rag` to drop `postgres_url` from the `_query_pgvector` call:

```python
async def retrieve_from_rag(state: SecondBrainState) -> RagRetrievalOutput:
    """LangGraph node: retrieves relevant chunks for the latest user message."""
    query = get_str_content(state["messages"][-1])
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding)
    return {"rag_results": rows}
```

Also update app lifespan (`apps/backend/src/second_brain/main.py` or wherever `shutdown_rag_pool` was called): replace `shutdown_rag_pool` import with `shutdown_pgvector_pool` from `second_brain.db.pool`.

Check for the lifespan call:

```bash
grep -rn "shutdown_rag_pool\|shutdown_pgvector_pool" apps/backend/src/
```

Replace any `shutdown_rag_pool` call with:

```python
from second_brain.db.pool import shutdown_pgvector_pool
# in lifespan: await shutdown_pgvector_pool()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd apps/backend && python -m pytest tests/unit/test_db/test_pool.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Run the full unit suite to confirm no regressions**

```bash
cd apps/backend && python -m pytest tests/unit/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 7: Update CLAUDE.md**

In `CLAUDE.md`, update the "Two Postgres connection pools" note to reflect the new pool location:

```markdown
# BEFORE:

- Two Postgres connection pools coexist: `asyncpg.Pool` in `nodes/rag_retrieval.py` ...

# AFTER:

- Two Postgres connection pools coexist: `asyncpg.Pool` in `db/pool.py` (shared by
  `rag_retrieval` and `memory_retrieval_node` via `get_pgvector_pool()`) and
  `psycopg_pool.AsyncConnectionPool` in `graphs/query_graph.py` (required by
  LangGraph's `AsyncPostgresSaver`). They cannot share a pool — different drivers.
```

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/second_brain/db/pool.py \
        apps/backend/src/second_brain/nodes/rag_retrieval.py \
        apps/backend/src/second_brain/main.py \
        apps/backend/tests/unit/test_db/__init__.py \
        apps/backend/tests/unit/test_db/test_pool.py \
        CLAUDE.md
git commit -m "refactor(db): extract shared asyncpg pool to db/pool.py; migrate rag_retrieval"
```

---

### Acceptance Criteria
(none listed in task section — task produces: get_pgvector_pool() -> asyncpg.Pool, shutdown_pgvector_pool() -> None)
