"""MemoryPersistenceNode: writes facts and corrections to the database.

Conflict-check reads: asyncpg pool (get_pgvector_pool)
Writes: SQLModel sync Session(engine) wrapped in asyncio.to_thread
Per-fact retry: up to _MAX_RETRIES attempts before raising
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlmodel import Session

from second_brain.config import settings
from second_brain.db.models import LearnedFact, ModelCorrection
from second_brain.db.pool import get_pgvector_pool
from second_brain.db.session import engine
from second_brain.graphs.state import CorrectionUpdate, FactUpdate, SecondBrainState
from second_brain.services.embeddings import embed_text

logger = logging.getLogger(__name__)
_MAX_RETRIES = 3


async def _conflict_check(embedding: list[float]) -> list[dict[str, Any]]:
    """Return rows from learned_facts whose cosine similarity exceeds threshold."""
    threshold = settings.memory_conflict_threshold
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
            " FROM learned_facts"
            " WHERE (embedding<=>$1) < (1 - $2)"
            " ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
            threshold,
        )
        return [dict(r) for r in rows]


def _retry_write(fn: Any, *args: Any) -> None:
    """Run a sync write function with up to _MAX_RETRIES attempts, then raise."""
    for attempt in range(_MAX_RETRIES):
        try:
            fn(*args)
            return
        except Exception as exc:
            logger.warning(
                "memory write attempt %d/%d failed: %s",
                attempt + 1,
                _MAX_RETRIES,
                exc,
                exc_info=True,
            )
            if attempt == _MAX_RETRIES - 1:
                raise


def _write_fact(
    fact_update: FactUpdate,
    session_id: str,
    embedding: list[float],
) -> None:
    with Session(engine) as session:
        # Delete replaced facts first (conflict resolution path)
        for cid in fact_update.get("conflicts_with") or []:
            row = session.get(LearnedFact, uuid.UUID(cid))
            if row:
                session.delete(row)
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
    correction: CorrectionUpdate,
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
    fact_update: FactUpdate,
    session_id: str,
    skip_conflict_check: bool = False,
) -> dict[str, Any] | None:
    """Persist one fact. Returns conflict dict on conflict, None on success.

    skip_conflict_check should be True when the caller is already in a
    conflict-resolution turn (awaiting_conflict_clarification=True).  This
    prevents _conflict_check from firing again when the LLM omitted the
    conflicts_with UUID, which would otherwise cause an infinite loop (F1).
    """
    embedding = await embed_text(fact_update["fact"])

    # conflicts_with non-empty → user resolved conflict; delete old facts then write.
    # skip_conflict_check → conflict was already handled last turn; write directly
    # even if the LLM omitted the UUID (prevents re-entering conflict state, F1 fix).
    if fact_update.get("conflicts_with") or skip_conflict_check:
        await asyncio.to_thread(
            _retry_write, _write_fact, fact_update, session_id, embedding
        )
        return None

    conflicts = await _conflict_check(embedding)
    if conflicts:
        return {
            "existing": conflicts[0]["fact"],
            "existing_id": conflicts[0]["id"],
            "new": fact_update["fact"],
        }

    await asyncio.to_thread(
        _retry_write, _write_fact, fact_update, session_id, embedding
    )
    return None


async def memory_persistence_node(state: SecondBrainState) -> dict[str, Any]:
    """Tool-call node: embeds and persists fact_updates + correction_updates."""
    fact_updates: list[FactUpdate] = state.get("fact_updates") or []
    correction_updates: list[CorrectionUpdate] = state.get("correction_updates") or []
    session_id: str = state["session_id"]
    final_answer: str = state.get("final_answer", "")

    # F1 fix: if we are resolving a conflict from a prior turn, skip _conflict_check
    # even when the LLM omits conflicts_with — prevents re-entering conflict state.
    coming_from_conflict: bool = state.get("awaiting_conflict_clarification", False)  # type: ignore[union-attr]

    conflict_contexts: list[dict[str, Any]] = []
    pending_facts: list[dict[str, Any]] = []

    for fact_update in fact_updates:
        conflict = await _persist_fact(
            fact_update, session_id, skip_conflict_check=coming_from_conflict
        )
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
        await asyncio.to_thread(
            _retry_write, _write_correction, correction, session_id, embedding
        )

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
