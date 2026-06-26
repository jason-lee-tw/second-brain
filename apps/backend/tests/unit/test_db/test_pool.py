from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_pgvector_pool_initialises_once():
    """Calling get_pgvector_pool() twice returns the same pool — only created once."""
    import second_brain.db.pool as pool_module

    saved = pool_module._pgvector_pool
    pool_module._pgvector_pool = None  # reset singleton for test isolation

    mock_pool = MagicMock()
    with patch(
        "second_brain.db.pool.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
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
