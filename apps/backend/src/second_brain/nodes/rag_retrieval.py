import asyncpg
from pgvector.asyncpg import register_vector

from second_brain.config import settings
from second_brain.graphs.state import RagResult, SecondBrainState
from second_brain.services.embeddings import embed_text

# Module-level connection pool singleton — created once on first query, reused
# across requests to avoid paying a TCP+auth handshake per /query call.
_pool: asyncpg.Pool | None = None


def _asyncpg_dsn(database_url: str) -> str:
    """asyncpg needs a bare postgresql:// DSN — strip the SQLAlchemy driver suffix."""
    return database_url.replace("+psycopg2", "")


async def _get_pool(postgres_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        # register_vector's signature is (conn, schema='public'), matching
        # asyncpg's per-connection `init` callback contract — it runs once for
        # every new physical connection the pool opens.
        _pool = await asyncpg.create_pool(postgres_url, init=register_vector)
    return _pool


async def shutdown() -> None:
    """Close the pgvector connection pool, if one was opened.

    Called from the FastAPI lifespan in main.py.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _query_pgvector(
    embedding: list[float], postgres_url: str, top_k: int = 5
) -> list[dict]:
    """Run cosine similarity search against document_chunks in pgvector."""
    pool = await _get_pool(postgres_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content,
                   1 - (embedding <=> $1) AS score,
                   chunk_index,
                   metadata
            FROM document_chunks
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            embedding,
            top_k,
        )
        return [
            {
                "content": row["content"],
                "score": float(row["score"]),
                "chunk_index": row["chunk_index"],
                "metadata": dict(row["metadata"]) if row["metadata"] else {},
            }
            for row in rows
        ]


async def retrieve_from_rag(state: SecondBrainState) -> dict:
    """Graph node: embed query via Ollama, cosine similarity search on document_chunks.

    Returns rag_results populated with RagResult items (top-k=5), sorted by
    descending score (the SQL ORDER BY already sorts by ascending distance,
    i.e. descending score).
    """
    query = state["messages"][-1].content
    embedding = await embed_text(query)
    rows = await _query_pgvector(embedding, _asyncpg_dsn(settings.database_url))

    rag_results: list[RagResult] = [
        {
            "content": row["content"],
            "score": row["score"],
            "chunk_index": row["chunk_index"],
            "metadata": row["metadata"],
        }
        for row in rows
    ]
    return {"rag_results": rag_results}
