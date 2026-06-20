"""Tests for SecondBrainState TypedDicts and RagResult structure."""

from langchain_core.messages import HumanMessage

from second_brain.graphs.state import (
    CorrectionUpdate,
    FactUpdate,
    MemoryItem,
    RagResult,
    SecondBrainState,
    WebResult,
)


def test_rag_result_construction():
    """RagResult TypedDict can be constructed with all required keys."""
    result: RagResult = {
        "content": "Some chunk content",
        "score": 0.87,
        "chunk_index": 2,
        "metadata": {"source": "file.md"},
    }
    assert result["content"] == "Some chunk content"
    assert result["score"] == 0.87
    assert result["chunk_index"] == 2
    assert result["metadata"] == {"source": "file.md"}


def test_web_result_construction():
    """WebResult TypedDict can be constructed with all required keys."""
    result: WebResult = {
        "title": "Example Article",
        "url": "https://example.com/article",
        "content": "Article body text",
    }
    assert result["title"] == "Example Article"
    assert result["url"] == "https://example.com/article"
    assert result["content"] == "Article body text"


def test_memory_item_construction():
    """MemoryItem TypedDict can be constructed with all required keys."""
    item: MemoryItem = {
        "id": "mem-001",
        "fact": "Python was created by Guido van Rossum",
        "confidence": 0.95,
        "type": "learned_fact",
    }
    assert item["id"] == "mem-001"
    assert item["type"] == "learned_fact"

    correction: MemoryItem = {
        "id": "mem-002",
        "fact": "The correction text",
        "confidence": 0.8,
        "type": "model_correction",
    }
    assert correction["type"] == "model_correction"


def test_fact_update_construction():
    """FactUpdate TypedDict can be constructed with all required keys."""
    update: FactUpdate = {
        "fact": "New discovered fact",
        "confidence": 0.9,
        "conflicts_with": ["old-fact-id-1"],
    }
    assert update["fact"] == "New discovered fact"
    assert update["conflicts_with"] == ["old-fact-id-1"]


def test_correction_update_construction():
    """CorrectionUpdate TypedDict can be constructed with all required keys."""
    update: CorrectionUpdate = {
        "original_answer": "Wrong answer",
        "correction": "Right answer",
        "root_cause": "Hallucination",
    }
    assert update["original_answer"] == "Wrong answer"
    assert update["correction"] == "Right answer"
    assert update["root_cause"] == "Hallucination"


def test_second_brain_state_minimal_construction():
    """SecondBrainState can be constructed with all required keys."""
    state: SecondBrainState = {
        "session_id": "test-session-001",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.9,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    assert state["session_id"] == "test-session-001"
    assert len(state["messages"]) == 1
    assert state["routing_decision"] == "neither"
    assert state["final_answer"] == ""
    assert state["confidence"] == 0.9


def test_second_brain_state_routing_decision_values():
    """SecondBrainState routing_decision accepts all valid Literal values."""
    for routing in ("rag", "web", "both", "neither"):
        state: SecondBrainState = {
            "session_id": "test-session-002",
            "messages": [],
            "rag_results": [],
            "web_results": [],
            "retrieved_memory": [],
            "routing_decision": routing,  # type: ignore[typeddict-item]
            "final_answer": "answer",
            "confidence": 0.7,
            "is_uncertain": True,
            "awaiting_correction": False,
            "awaiting_conflict_clarification": False,
            "conflict_context": [],
            "fact_updates": [],
            "correction_updates": [],
        }
        assert state["routing_decision"] == routing


def test_second_brain_state_with_rag_results():
    """SecondBrainState accepts non-empty rag_results and web_results."""
    rag: RagResult = {
        "content": "chunk text",
        "score": 0.92,
        "chunk_index": 0,
        "metadata": {},
    }
    web: WebResult = {
        "title": "Page Title",
        "url": "https://example.com",
        "content": "page content",
    }
    state: SecondBrainState = {
        "session_id": "s-003",
        "messages": [],
        "rag_results": [rag],
        "web_results": [web],
        "retrieved_memory": [],
        "routing_decision": "both",
        "final_answer": "combined answer",
        "confidence": 0.85,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    assert len(state["rag_results"]) == 1
    assert state["rag_results"][0]["score"] == 0.92
    assert len(state["web_results"]) == 1
    assert state["web_results"][0]["url"] == "https://example.com"
