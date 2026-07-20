from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.nodes.synthesis import synthesize_answer
from tests.unit.conftest import make_state


def _mock_synthesis(answer: str, confidence: float):
    mock = MagicMock()
    mock.final_answer = answer
    mock.confidence = confidence
    return mock


@pytest.mark.asyncio
async def test_returns_final_answer_and_confidence():
    state = make_state(
        messages=[HumanMessage(content="What is LangGraph?")],
        rag_results=[
            {
                "content": "LangGraph is a graph-based agent framework.",
                "score": 0.9,
                "chunk_index": 0,
                "metadata": {},
            }
        ],
        web_results=[],
        retrieved_memory=[],
        routing_decision="rag",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(
            return_value=_mock_synthesis("LangGraph is a framework for agents.", 0.85)
        )
        result = await synthesize_answer(state)

    assert result["final_answer"] == "LangGraph is a framework for agents."
    assert result["confidence"] == 0.85
    assert result["is_uncertain"] is False


@pytest.mark.asyncio
async def test_is_uncertain_true_when_confidence_below_07():
    state = make_state(
        messages=[HumanMessage(content="What is the best diet?")],
        rag_results=[],
        web_results=[],
        retrieved_memory=[],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(
            return_value=_mock_synthesis("It depends on the individual.", 0.65)
        )
        result = await synthesize_answer(state)

    assert result["is_uncertain"] is True
    assert result["confidence"] == 0.65


@pytest.mark.asyncio
async def test_neither_routing_applies_confidence_floor_of_05():
    """AC: when routing_decision == 'neither', confidence is floored at 0.5."""
    state = make_state(
        messages=[HumanMessage(content="Hey there!")],
        rag_results=[],
        web_results=[],
        retrieved_memory=[],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        # LLM returns very low confidence (e.g. 0.2) — should be raised to 0.5
        mock_llm.ainvoke = AsyncMock(
            return_value=_mock_synthesis("Hello! How can I help?", 0.2)
        )
        result = await synthesize_answer(state)

    assert result["confidence"] == 0.5
    assert result["is_uncertain"] is True  # 0.5 < 0.7, still uncertain
    assert result["final_answer"] == "Hello! How can I help?"


@pytest.mark.asyncio
async def test_neither_routing_does_not_lower_confidence_above_floor():
    """If LLM returns confidence > 0.5 on 'neither' routing, keep the LLM value."""
    state = make_state(
        messages=[HumanMessage(content="What is 2 + 2?")],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("4", 0.99))
        result = await synthesize_answer(state)

    assert result["confidence"] == 0.99


@pytest.mark.asyncio
async def test_trims_messages_to_last_10():
    """Verify only the last 10 messages are included in the synthesis prompt."""
    messages = [HumanMessage(content=f"Message {i}") for i in range(15)]
    state = make_state(
        messages=messages,
        routing_decision="neither",
    )
    captured_prompts: list[str] = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return _mock_synthesis("answer", 0.8)

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = capture_invoke
        await synthesize_answer(state)

    # "Message 0" through "Message 4" should NOT be in the prompt
    assert "Message 0" not in captured_prompts[0]
    assert "Message 5" in captured_prompts[0]
