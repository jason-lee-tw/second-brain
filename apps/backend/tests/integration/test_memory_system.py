"""Integration tests for the full memory cycle.

Requires: Docker stack running (PostgreSQL + pgvector + Ollama).
Uses the same DB skip guard as existing integration tests.

Run with:
  DATABASE_URL=postgresql+asyncpg://second_brain:secret@localhost:5432/second_brain \
    pytest tests/integration/test_memory_system.py -v -m integration
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

_TEST_SESSION_ID = "integration-memory-test"


@pytest.fixture(scope="module")
def db_engine():
    """Connect to the real Postgres. Skip if DATABASE_URL is a test placeholder."""
    url = _DATABASE_URL
    if "test-api-key" in url or ("localhost" not in url and "app_postgres" not in url):
        pytest.skip(
            "DATABASE_URL does not point to a real running database"
            " — skipping memory system integration test"
        )
    # Strip asyncpg driver suffix — sync SQLAlchemy doesn't support it
    sync_url = url.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_test_rows(db_engine):
    """Delete rows written by this test session before each test."""
    with db_engine.connect() as conn:
        conn.execute(
            text("DELETE FROM learned_facts WHERE source_session = :sid"),
            {"sid": _TEST_SESSION_ID},
        )
        conn.execute(
            text("DELETE FROM model_corrections WHERE source_session = :sid"),
            {"sid": _TEST_SESSION_ID},
        )
        conn.commit()
    yield


def _make_state(**overrides):  # type: ignore[return]
    from langchain_core.messages import HumanMessage

    from second_brain.graphs.state import SecondBrainState

    base: SecondBrainState = {
        "session_id": _TEST_SESSION_ID,
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "Test answer.",
        "confidence": 0.9,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


async def test_ac1_fact_written_to_db_with_embedding(db_engine):
    """AC-1: fact_updates → learned_facts row with 1024-dim non-zero embedding."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[
            {
                "fact": "The user is a vegetarian.",
                "confidence": 0.95,
                "conflicts_with": [],
            },
            {
                "fact": "The user loves hiking.",
                "confidence": 0.9,
                "conflicts_with": [],
            },
        ],
    )
    await memory_persistence_node(state)

    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT fact, confidence, embedding"
                " FROM learned_facts"
                " WHERE source_session = :sid"
            ),
            {"sid": _TEST_SESSION_ID},
        ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row.embedding is not None
        assert len(row.embedding) == 1024
        assert any(x != 0.0 for x in row.embedding)


async def test_ac2_conflict_detected_not_written(db_engine):
    """AC-2: pre-seed a fact; add semantically similar fact.

    Expected: conflict detected, new fact not written.
    """
    from sqlmodel import Session

    from second_brain.db.models import LearnedFact
    from second_brain.db.session import engine as sqlmodel_engine
    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.services.embeddings import embed_text

    # Seed existing fact
    embedding = await embed_text("The user lives in Berlin.")
    with Session(sqlmodel_engine) as session:
        session.add(
            LearnedFact(
                id=uuid.uuid4(),
                fact="The user lives in Berlin.",
                embedding=embedding,
                source_session=_TEST_SESSION_ID,
                confidence=0.9,
            )
        )
        session.commit()

    # Attempt to add semantically similar fact
    state = _make_state(
        final_answer="You mentioned moving.",
        fact_updates=[
            {
                "fact": "The user lives in Berlin now.",
                "confidence": 0.85,
                "conflicts_with": [],
            }
        ],
    )
    result = await memory_persistence_node(state)

    assert result["awaiting_conflict_clarification"] is True
    assert "⚠️" in result["final_answer"]

    with db_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*)"
                " FROM learned_facts"
                " WHERE source_session = :sid AND fact LIKE '%now%'"
            ),
            {"sid": _TEST_SESSION_ID},
        ).scalar()
    assert count == 0


async def test_ac4_correction_written_with_embedding(db_engine):
    """AC-4: correction_updates → model_corrections row with correction embedding."""
    from second_brain.nodes.memory_persistence import memory_persistence_node

    state = _make_state(
        fact_updates=[],
        correction_updates=[
            {
                "original_answer": "The speed of light is 100 km/s.",
                "correction": "The speed of light is approximately 299,792 km/s.",
                "root_cause": "AI used an incorrect value.",
            }
        ],
    )
    await memory_persistence_node(state)

    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT correction, root_cause, embedding"
                " FROM model_corrections"
                " WHERE source_session = :sid"
            ),
            {"sid": _TEST_SESSION_ID},
        ).fetchall()

    assert len(rows) == 1
    assert "299,792" in rows[0].correction
    assert rows[0].root_cause == "AI used an incorrect value."
    assert rows[0].embedding is not None
    assert len(rows[0].embedding) == 1024


async def test_full_memory_loop_persist_then_retrieve(db_engine):  # noqa: ARG001
    """Full loop: persist fact → retrieve on related query → fact in memory."""
    from langchain_core.messages import HumanMessage

    from second_brain.nodes.memory_persistence import memory_persistence_node
    from second_brain.nodes.memory_retrieval import memory_retrieval_node

    # Turn 1: persist
    await memory_persistence_node(
        _make_state(
            fact_updates=[
                {
                    "fact": "The user is a professional cyclist.",
                    "confidence": 0.9,
                    "conflicts_with": [],
                }
            ],
        )
    )

    # Turn 2: retrieve
    result = await memory_retrieval_node(
        _make_state(messages=[HumanMessage(content="What sports do I do?")])
    )

    retrieved = result["retrieved_memory"]
    assert len(retrieved) >= 1
    assert any("cyclist" in item["fact"].lower() for item in retrieved)
