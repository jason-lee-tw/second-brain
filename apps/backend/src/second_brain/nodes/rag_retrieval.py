"""RAG retrieval node: embeds the user query and fetches top-k chunks via pgvector."""

# ponytail: separate asyncpg pool — pgvector.asyncpg requires asyncpg; LangGraph
# PostgresSaver requires psycopg3 (psycopg_pool); these two drivers can't share a pool

import asyncio

import asyncpg
import httpx
from pgvector.asyncpg import register_vector

from second_brain.config import settings
from second_brain.graphs.state import RagResult, RagRetrievalOutput, SecondBrainState
from second_brain.services.chunking import ChunkMetadata
from second_brain.utils import get_str_content

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


def _row_to_chunk_metadata(row_meta: object) -> ChunkMetadata:
    d: dict[str, object] = dict(row_meta)  # pyright: ignore[reportCallIssue, reportAssignmentType, reportArgumentType]
    return {
        "source": str(d["source"]),
        "heading_path": str(d["heading_path"]),
        "content_type": str(d["content_type"]),
        "char_count": int(d["char_count"]),  # pyright: ignore[reportArgumentType]
    }


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
) -> list[RagResult]:
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


async def retrieve_from_rag(state: SecondBrainState) -> RagRetrievalOutput:
    """LangGraph node: retrieves relevant chunks for the latest user message."""
    query = get_str_content(state["messages"][-1])
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding, settings.postgres_url)
    return {"rag_results": rows}
