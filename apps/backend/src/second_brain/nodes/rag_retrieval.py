"""RAG retrieval node: embeds the user query and fetches top-k chunks via pgvector."""

import asyncio

import asyncpg
import httpx
from pgvector.asyncpg import register_vector

from second_brain.config import settings
from second_brain.graphs.state import SecondBrainState

_rag_pool: asyncpg.Pool | None = None
_rag_pool_lock: asyncio.Lock = asyncio.Lock()


async def _get_rag_pool(postgres_url: str) -> asyncpg.Pool:
    """Return the module-level connection pool, initialising it on first call."""
    global _rag_pool
    async with _rag_pool_lock:
        if _rag_pool is None:
            _rag_pool = await asyncpg.create_pool(postgres_url, init=register_vector)
    return _rag_pool


async def shutdown_rag_pool() -> None:
    """Close the module-level pool and reset the singleton to None."""
    global _rag_pool
    if _rag_pool is not None:
        await _rag_pool.close()
        _rag_pool = None


async def _embed_query(query: str, base_url: str) -> list[float]:
    """Call the local Ollama embedding endpoint and return the embedding vector."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/embeddings",
            json={"model": "qwen3-embedding:0.6b", "prompt": query},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


async def _query_pgvector(
    embedding: list[float], postgres_url: str, top_k: int = 5
) -> list[dict]:
    """Query the document_chunks table for the top-k most similar chunks."""
    pool = await _get_rag_pool(postgres_url)
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
                "score": float(r["score"]),
                "chunk_index": r["chunk_index"],
                "metadata": dict(r["metadata"]) if r["metadata"] else {},
            }
            for r in rows
        ]


async def retrieve_from_rag(state: SecondBrainState) -> dict:
    """LangGraph node: retrieves relevant chunks for the latest user message."""
    query = state["messages"][-1].content
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding, settings.postgres_url)
    return {"rag_results": rows}
