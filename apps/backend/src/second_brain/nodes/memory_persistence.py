"""MemoryPersistenceNode: writes facts and corrections to the database.

Conflict-check reads: asyncpg pool (get_pgvector_pool)
Writes: SQLModel sync Session(engine) — matches ingestion_agent.py pattern
Per-fact retry: up to _MAX_RETRIES attempts before raising
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session

from second_brain.config import settings
from second_brain.db.models import LearnedFact, ModelCorrection
from second_brain.db.pool import get_pgvector_pool
from second_brain.db.session import engine
from second_brain.graphs.state import SecondBrainState
from second_brain.services.embeddings import embed_text

_MAX_RETRIES = 3
_CONFLICT_THRESHOLD: float = settings.memory_conflict_threshold


async def _conflict_check(embedding: list[float]) -> list[dict[str, Any]]:
    """Return rows from learned_facts whose cosine similarity exceeds threshold."""
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
            " FROM learned_facts"
            " WHERE (embedding<=>$1) < (1 - $2)"
            " ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
            _CONFLICT_THRESHOLD,
        )
        return [dict(r) for r in rows]


def _retry_write(fn: Any, *args: Any) -> None:
    """Run a sync write function with up to _MAX_RETRIES attempts, then raise."""
    for attempt in range(_MAX_RETRIES):
        try:
            fn(*args)
            return
        except Exception:
            if attempt == _MAX_RETRIES - 1:
                raise


def _write_fact(
    fact_update: dict[str, Any],
    session_id: str,
    embedding: list[float],
) -> None:
    with Session(engine) as session:
        session.add(
            LearnedFact(
                id=uuid.uuid4(),
                fact=fact_update["fact"],
                embedding=embedding,
                source_session=session_id,
                confidence=fact_update["confidence"],
            )
        )
        session.commit()


def _write_correction(
    correction: dict[str, Any],
    session_id: str,
    embedding: list[float],
) -> None:
    with Session(engine) as session:
        session.add(
            ModelCorrection(
                id=uuid.uuid4(),
                original_answer=correction["original_answer"],
                correction=correction["correction"],
                root_cause=correction["root_cause"],
                embedding=embedding,
                source_session=session_id,
            )
        )
        session.commit()


async def _persist_fact(
    fact_update: dict[str, Any],
    session_id: str,
) -> dict[str, Any] | None:
    """Persist one fact. Returns conflict dict on conflict, None on success."""
    embedding = await embed_text(fact_update["fact"])

    # conflicts_with is non-empty → user already resolved conflict, write directly
    conflicts_with: list[str] = fact_update["conflicts_with"]
    if conflicts_with:
        _retry_write(_write_fact, fact_update, session_id, embedding)
        return None

    conflicts = await _conflict_check(embedding)
    if conflicts:
        return {
            "existing": conflicts[0]["fact"],
            "existing_id": conflicts[0]["id"],
            "new": fact_update["fact"],
        }

    _retry_write(_write_fact, fact_update, session_id, embedding)
    return None


async def memory_persistence_node(state: SecondBrainState) -> dict[str, Any]:
    """Tool-call node: embeds and persists fact_updates + correction_updates."""
    fact_updates: list[dict[str, Any]] = list(state.get("fact_updates") or [])
    correction_updates: list[dict[str, Any]] = list(
        state.get("correction_updates") or []
    )
    session_id: str = state["session_id"]
    final_answer: str = state.get("final_answer", "")

    conflict_contexts: list[dict[str, Any]] = []
    pending_facts: list[dict[str, Any]] = []

    for fact_update in fact_updates:
        conflict = await _persist_fact(fact_update, session_id)
        if conflict is not None:
            conflict_contexts.append(conflict)
            pending_facts.append(
                {
                    "fact": fact_update["fact"],
                    "confidence": fact_update["confidence"],
                    "conflicts_with": [conflict["existing_id"]],
                }
            )

    for correction in correction_updates:
        embedding = await embed_text(correction["correction"])
        _retry_write(_write_correction, correction, session_id, embedding)

    # Set awaiting_correction AFTER memory_agent so the flag is available in the
    # NEXT turn's memory_agent (cross-turn correction detection).
    result: dict[str, Any] = {
        "awaiting_correction": state.get("is_uncertain", False),
        "awaiting_conflict_clarification": bool(conflict_contexts),
        "conflict_context": conflict_contexts,
        "fact_updates": pending_facts if conflict_contexts else [],
        "correction_updates": [],
    }

    if conflict_contexts:
        conflict_msg = "\n\n⚠️ I noticed potential conflicts with existing memory:\n"
        for c in conflict_contexts:
            conflict_msg += f'- Existing: "{c["existing"]}" | New: "{c["new"]}"\n'
        conflict_msg += "Please clarify which is correct (or if both apply)."
        result["final_answer"] = final_answer + conflict_msg

    return result
