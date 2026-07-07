"""RAG retrieval node: embeds the user query and fetches top-k chunks via pgvector."""

from typing import override

import httpx

from second_brain.config import settings
from second_brain.db.pool import get_pgvector_pool
from second_brain.graphs.state import RagResult, RagRetrievalOutput, SecondBrainState
from second_brain.nodes.base_node import BaseNode
from second_brain.services.chunking import ChunkMetadata
from second_brain.utils import get_str_content


def _row_to_chunk_metadata(row_meta: object) -> ChunkMetadata:
  # asyncpg.Record has no stubs; dict() triggers 3 pyright codes, same root cause
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


class RagRetrievalNode(BaseNode[SecondBrainState, RagRetrievalOutput]):
  """Retrieves relevant chunks for the latest user message."""

  @override
  async def __call__(self, state: SecondBrainState) -> RagRetrievalOutput:
    query = get_str_content(state["messages"][-1])
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding)
    return {"rag_results": rows}


retrieve_from_rag = RagRetrievalNode()
