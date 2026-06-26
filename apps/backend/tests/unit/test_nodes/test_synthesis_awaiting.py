from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from second_brain.graphs.state import SecondBrainState
from second_brain.nodes.synthesis import synthesize_answer


def _make_state(**overrides) -> SecondBrainState:
    base: SecondBrainState = {
        "session_id": "test",
        "messages": [HumanMessage(content="What is the capital of France?")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "fact_updates": [],
        "correction_updates": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_synthesis_sets_awaiting_correction_when_uncertain():
    """D9: confidence < 0.7 → is_uncertain=True AND awaiting_correction=True."""
    from second_brain.nodes.synthesis import _SynthesisOutput

    mock_output = MagicMock(spec=_SynthesisOutput)
    mock_output.final_answer = "I'm not sure."
    mock_output.confidence = 0.5
    mock_output.reasoning = "Limited context."

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        result = await synthesize_answer(_make_state())

    assert result["is_uncertain"] is True
    assert result["awaiting_correction"] is True


@pytest.mark.asyncio
async def test_synthesis_does_not_set_awaiting_correction_when_confident():
    """confidence >= 0.7 → is_uncertain=False AND awaiting_correction=False."""
    from second_brain.nodes.synthesis import _SynthesisOutput

    mock_output = MagicMock(spec=_SynthesisOutput)
    mock_output.final_answer = "Paris."
    mock_output.confidence = 0.95
    mock_output.reasoning = "Well established."

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        result = await synthesize_answer(_make_state())

    assert result["is_uncertain"] is False
    assert result["awaiting_correction"] is False
