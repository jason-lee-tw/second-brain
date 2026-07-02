"""Unit tests for the synthesis node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tests.unit.conftest import make_state

# ---------------------------------------------------------------------------
# TDD tests: _format_messages helper
# Tests (a) and (b) per the approved plan.
# ---------------------------------------------------------------------------


def test_format_messages_str_content_passes_through():
    """_format_messages works correctly for normal string-content messages.

    Regression guard — expected GREEN before and after the fix.
    """
    from second_brain.nodes.synthesis import _format_messages

    messages = [HumanMessage(content="hello"), AIMessage(content="world")]
    result = _format_messages(messages)

    assert "hello" in result
    assert "world" in result


def test_format_messages_raises_on_list_content():
    """_format_messages raises TypeError when a message has list (multi-modal) content.

    Expected RED before fix (bare .content silently formats list),
    GREEN after fix (get_str_content raises TypeError).
    """
    from second_brain.nodes.synthesis import _format_messages

    msg = AIMessage(content=[{"type": "text", "text": "hi"}])
    with pytest.raises(TypeError):
        _format_messages([msg])


# ---------------------------------------------------------------------------
# TDD test (c): synthesize_answer raises TypeError on list-content query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_answer_raises_on_list_content_query():
    """synthesize_answer raises TypeError when the last message has list content.

    Expected RED before fix (bare .content silently assigns the list),
    GREEN after fix (get_str_content raises TypeError).

    Uses a proper AsyncMock so the TypeError must come from get_str_content,
    not from awaiting a plain MagicMock.
    """
    mock_output = _make_synthesis_output(
        final_answer="some answer",
        confidence=0.8,
        reasoning="ok",
    )
    state = make_state(
        messages=[HumanMessage(content=[{"type": "text", "text": "hi"}])],
        routing_decision="rag",
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        with pytest.raises(TypeError):
            await synthesize_answer(state)


def _make_synthesis_output(final_answer: str, confidence: float, reasoning: str):
    """Create a mock _SynthesisOutput-like object."""
    obj = MagicMock()
    obj.final_answer = final_answer
    obj.confidence = confidence
    obj.reasoning = reasoning
    return obj


@pytest.mark.asyncio
async def test_synthesize_answer_returns_answer_and_confidence():
    """synthesize_answer returns final_answer and confidence from the LLM."""
    mock_output = _make_synthesis_output(
        final_answer="Paris is the capital of France.",
        confidence=0.9,
        reasoning="Well-known geographical fact.",
    )

    state = make_state(
        messages=[HumanMessage(content="What is the capital of France?")],
        routing_decision="rag",
        rag_results=[
            {
                "content": "Paris is the capital.",
                "score": 0.95,
                "chunk_index": 0,
                "metadata": {},
            }
        ],
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["final_answer"] == "Paris is the capital of France."
    assert result["confidence"] == 0.9
    assert "is_uncertain" in result


@pytest.mark.asyncio
async def test_synthesize_answer_is_uncertain_when_confidence_below_threshold():
    """is_uncertain is True when confidence < 0.7."""
    mock_output = _make_synthesis_output(
        final_answer="I'm not sure.",
        confidence=0.5,
        reasoning="Insufficient information.",
    )

    state = make_state(
        messages=[HumanMessage(content="What happened yesterday?")],
        routing_decision="web",
        web_results=[
            {"title": "News", "url": "http://example.com", "content": "Some news."}
        ],
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["is_uncertain"] is True
    assert result["confidence"] == 0.5


@pytest.mark.asyncio
async def test_synthesize_answer_applies_confidence_floor_for_neither_routing():
    """For 'neither' routing, confidence is floored at 0.5 even if LLM returns lower."""
    mock_output = _make_synthesis_output(
        final_answer="I don't have specific information.",
        confidence=0.3,
        reasoning="No relevant data.",
    )

    state = make_state(
        messages=[HumanMessage(content="What is the weather on Mars?")],
        routing_decision="neither",
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    # Floor should raise 0.3 to 0.5
    assert result["confidence"] == 0.5
    # Still uncertain since 0.5 < 0.7
    assert result["is_uncertain"] is True


@pytest.mark.asyncio
async def test_synthesize_answer_floor_does_not_lower_confidence_above_floor():
    """For 'neither' routing, confidence floor does NOT lower a value above 0.5."""
    mock_output = _make_synthesis_output(
        final_answer="Here is some general information.",
        confidence=0.8,
        reasoning="Reasonable general answer.",
    )

    state = make_state(
        messages=[HumanMessage(content="Tell me something general.")],
        routing_decision="neither",
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    # Floor should NOT lower 0.8 to 0.5
    assert result["confidence"] == 0.8
    assert result["is_uncertain"] is False


@pytest.mark.asyncio
async def test_synthesize_answer_trims_messages_to_last_10():
    """synthesize_answer only uses the last 10 messages for conversation history."""
    # Create 15 messages (alternating Human/AI), last one is the query
    messages = []
    for i in range(7):
        messages.append(HumanMessage(content=f"Question {i}"))
        messages.append(AIMessage(content=f"Answer {i}"))
    messages.append(HumanMessage(content="Final query"))  # 15th message

    mock_output = _make_synthesis_output(
        final_answer="Answer to final query.",
        confidence=0.85,
        reasoning="Based on context.",
    )

    state = make_state(
        messages=messages,
        routing_decision="rag",
        rag_results=[
            {
                "content": "Relevant info.",
                "score": 0.9,
                "chunk_index": 0,
                "metadata": {},
            }
        ],
    )

    captured_prompt = []

    async def capture_invoke(prompt):
        captured_prompt.append(prompt)
        return mock_output

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(side_effect=capture_invoke)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["final_answer"] == "Answer to final query."
    # The prompt should contain only the last 10 messages, not all 15
    assert len(captured_prompt) == 1
    prompt_text = str(captured_prompt[0])
    # Earlier messages should NOT be in conversation history
    assert "Question 0" not in prompt_text
    assert "Question 1" not in prompt_text


# ---------------------------------------------------------------------------
# context_used: single source of truth for grounding text fed to the LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_answer_context_used_rag_only():
    """context_used contains the raw RAG chunk content (no per-item annotation)."""
    mock_output = _make_synthesis_output(
        final_answer="answer", confidence=0.9, reasoning="ok"
    )
    state = make_state(
        messages=[HumanMessage(content="query")],
        routing_decision="rag",
        rag_results=[
            {
                "content": "Paris is the capital.",
                "score": 0.95,
                "chunk_index": 0,
                "metadata": {},
            }
        ],
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["context_used"] == ["Paris is the capital."]


@pytest.mark.asyncio
async def test_synthesize_answer_context_used_web_only():
    """context_used contains the formatted **title** (url)\\ncontent string."""
    mock_output = _make_synthesis_output(
        final_answer="answer", confidence=0.9, reasoning="ok"
    )
    state = make_state(
        messages=[HumanMessage(content="query")],
        routing_decision="web",
        web_results=[
            {"title": "News", "url": "http://example.com", "content": "Some news."}
        ],
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["context_used"] == ["**News** (http://example.com)\nSome news."]


@pytest.mark.asyncio
async def test_synthesize_answer_context_used_memory_only():
    """context_used contains the formatted "- fact (confidence: X.XX)" string."""
    mock_output = _make_synthesis_output(
        final_answer="answer", confidence=0.9, reasoning="ok"
    )
    state = make_state(
        messages=[HumanMessage(content="query")],
        routing_decision="neither",
        retrieved_memory=[
            {
                "id": "1",
                "fact": "User likes Paris.",
                "confidence": 0.8,
                "type": "learned_fact",
            }
        ],
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["context_used"] == ["- User likes Paris. (confidence: 0.80)"]


@pytest.mark.asyncio
async def test_synthesize_answer_context_used_combines_all_three_in_order():
    """context_used concatenates rag -> web -> memory, in that order."""
    mock_output = _make_synthesis_output(
        final_answer="answer", confidence=0.9, reasoning="ok"
    )
    state = make_state(
        messages=[HumanMessage(content="query")],
        routing_decision="both",
        rag_results=[
            {
                "content": "RAG chunk.",
                "score": 0.9,
                "chunk_index": 0,
                "metadata": {},
            }
        ],
        web_results=[
            {"title": "Title", "url": "http://x.com", "content": "Web content."}
        ],
        retrieved_memory=[
            {
                "id": "1",
                "fact": "A fact.",
                "confidence": 0.5,
                "type": "learned_fact",
            }
        ],
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["context_used"] == [
        "RAG chunk.",
        "**Title** (http://x.com)\nWeb content.",
        "- A fact. (confidence: 0.50)",
    ]


@pytest.mark.asyncio
async def test_synthesize_answer_context_used_empty_when_no_context():
    """context_used is an empty list when no rag/web/memory context is present."""
    mock_output = _make_synthesis_output(
        final_answer="answer", confidence=0.5, reasoning="ok"
    )
    state = make_state(
        messages=[HumanMessage(content="query")],
        routing_decision="neither",
    )

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        from second_brain.nodes.synthesis import synthesize_answer

        result = await synthesize_answer(state)

    assert result["context_used"] == []
