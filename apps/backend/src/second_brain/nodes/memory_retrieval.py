"""MemoryRetrievalNode: dual-table cosine search.

Searches learned_facts + model_corrections tables.
"""

import asyncio

import asyncpg
from langchain_core.messages import HumanMessage

from second_brain.db.pool import get_pgvector_pool
from second_brain.graphs.state import MemoryItem, RetrieveMemoryOutput, SecondBrainState
from second_brain.services.embeddings import embed_text
from second_brain.utils import get_str_content


async def _search_facts(
    pool: asyncpg.Pool, embedding: list[float]
) -> list[tuple[float, MemoryItem]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score"
            " FROM learned_facts ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
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
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, correction AS fact, 1-(embedding<=>$1) AS score"
            " FROM model_corrections ORDER BY embedding<=>$1 ASC LIMIT 3",
            embedding,
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


async def memory_retrieval_node(state: SecondBrainState) -> RetrieveMemoryOutput:
    """Embed current query and run two parallel cosine searches.

    Fails hard on Ollama unavailability — no empty-list fallback.
    """
    last_human: HumanMessage | None = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_human = msg
            break
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
