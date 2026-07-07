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
