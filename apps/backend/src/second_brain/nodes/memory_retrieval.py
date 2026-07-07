"""MemoryRetrievalNode: dual-table cosine search.

Searches learned_facts + model_corrections tables.
"""

import asyncio
from typing import override

import asyncpg

from second_brain.config import settings
from second_brain.db.pool import get_pgvector_pool
from second_brain.graphs.state import MemoryItem, RetrieveMemoryOutput, SecondBrainState
from second_brain.nodes.base_node import BaseNode
from second_brain.services.embeddings import embed_text
from second_brain.utils import get_str_content, last_human_message


async def _search_facts(
  pool: asyncpg.Pool, embedding: list[float]
) -> list[tuple[float, MemoryItem]]:
  max_distance = 1 - settings.memory_retrieval_threshold
  async with pool.acquire() as conn:
    rows = await conn.fetch(
      "SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score"
      " FROM learned_facts"
      " WHERE (embedding<=>$1) < $2"
      " ORDER BY embedding<=>$1 ASC LIMIT 5",
      embedding,
      max_distance,
    )
    return [
      (
        float(r["score"]),
        MemoryItem(
          id=r["id"],
          fact=r["fact"],
          confidence=r["confidence"],
          type="learned_fact",
        ),
      )
      for r in rows
    ]


async def _search_corrections(
  pool: asyncpg.Pool, embedding: list[float]
) -> list[tuple[float, MemoryItem]]:
  max_distance = 1 - settings.memory_retrieval_threshold
  async with pool.acquire() as conn:
    rows = await conn.fetch(
      "SELECT id::text, correction AS fact, 1-(embedding<=>$1) AS score"
      " FROM model_corrections"
      " WHERE (embedding<=>$1) < $2"
      " ORDER BY embedding<=>$1 ASC LIMIT 3",
      embedding,
      max_distance,
    )
    return [
      (
        float(r["score"]),
        MemoryItem(
          id=r["id"],
          fact=r["fact"],
          confidence=1.0,
          type="model_correction",
        ),
      )
      for r in rows
    ]


class MemoryRetrievalNode(BaseNode[SecondBrainState, RetrieveMemoryOutput]):
  """Embed current query and run two parallel cosine searches.

  Fails hard on Ollama unavailability — no empty-list fallback.
  """

  @override
  async def __call__(self, state: SecondBrainState) -> RetrieveMemoryOutput:
    last_human = last_human_message(state["messages"])
    if last_human is None:
      return {"retrieved_memory": []}

    query_text = get_str_content(last_human)
    embedding = await embed_text(query_text)  # raises if Ollama is down

    pool = await get_pgvector_pool()
    facts_scored, corrections_scored = await asyncio.gather(
      _search_facts(pool, embedding),
      _search_corrections(pool, embedding),
    )

    all_scored = sorted(
      facts_scored + corrections_scored, key=lambda x: x[0], reverse=True
    )
    return {"retrieved_memory": [item for _, item in all_scored]}


memory_retrieval_node = MemoryRetrievalNode()
