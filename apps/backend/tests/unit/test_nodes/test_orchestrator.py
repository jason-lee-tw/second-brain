# apps/backend/tests/unit/test_nodes/test_orchestrator.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.nodes.orchestrator import route_query
from tests.unit.conftest import make_state


def _mock_routing(decision: str):
    """Helper: create a mock RoutingOutput with the given routing_decision."""
    mock_result = MagicMock()
    mock_result.routing_decision = decision
    return mock_result


@pytest.mark.asyncio
async def test_routes_to_rag_for_personal_knowledge_query():
    state = make_state(
        messages=[HumanMessage(content="What are my notes on machine learning?")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("rag"))
        result = await route_query(state)
    assert result["routing_decision"] == "rag"


@pytest.mark.asyncio
async def test_routes_to_web_for_current_events():
    state = make_state(
        messages=[
            HumanMessage(content="What happened in the tech industry this week?")
        ],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("web"))
        result = await route_query(state)
    assert result["routing_decision"] == "web"


@pytest.mark.asyncio
async def test_routes_to_both_for_mixed_query():
    state = make_state(
        messages=[
            HumanMessage(
                content="Compare my notes on Python with the latest Python 4 news."
            )
        ],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("both"))
        result = await route_query(state)
    assert result["routing_decision"] == "both"


@pytest.mark.asyncio
async def test_routes_to_neither_for_conversational_query():
    state = make_state(
        messages=[HumanMessage(content="Thanks, that helps!")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
        result = await route_query(state)
    assert result["routing_decision"] == "neither"


@pytest.mark.asyncio
async def test_includes_memory_context_in_prompt():
    """Verify that retrieved_memory facts are passed to the LLM."""
    state = make_state(
        messages=[HumanMessage(content="What do I know about Rust?")],
        retrieved_memory=[
            {
                "id": "1",
                "fact": "User prefers Rust for systems programming",
                "confidence": 0.9,
                "type": "learned_fact",
            }
        ],
    )
    captured_prompts = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return _mock_routing("rag")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = capture_invoke
        await route_query(state)

    assert len(captured_prompts) == 1
    assert "User prefers Rust for systems programming" in captured_prompts[0]
