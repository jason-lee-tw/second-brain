# apps/backend/tests/unit/test_graphs/test_state.py
from langchain_core.messages import HumanMessage

from second_brain.graphs.state import (
    FailedFile,
    IngestionState,
    RagResult,
    SecondBrainState,
)


def test_failed_file_typeddict_construction():
    """FailedFile can be constructed with all required keys."""
    item: FailedFile = {
        "filename": "broken.md",
        "error": "Connection refused",
        "retry_count": 2,
    }
    assert item["filename"] == "broken.md"
    assert item["error"] == "Connection refused"
    assert item["retry_count"] == 2


def test_ingestion_state_typeddict_construction():
    """IngestionState can be constructed with all required keys."""
    state: IngestionState = {
        "files": ["a.md", "b.md"],
        "in_progress": None,
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }
    assert state["files"] == ["a.md", "b.md"]
    assert state["in_progress"] is None
    assert state["processed"] == []
    assert state["retry_queue"] == []
    assert state["failed"] == []


def test_ingestion_state_with_failed_file_in_retry_queue():
    """IngestionState retry_queue accepts FailedFile dicts."""
    failed: FailedFile = {"filename": "c.md", "error": "Timeout", "retry_count": 1}
    state: IngestionState = {
        "files": [],
        "in_progress": "c.md",
        "processed": ["a.md"],
        "retry_queue": [failed],
        "failed": [],
    }
    assert state["retry_queue"][0]["retry_count"] == 1


def test_ingestion_state_with_source_urls():
    """IngestionState accepts optional source_urls mapping."""
    state: IngestionState = {
        "files": [],
        "in_progress": None,
        "processed": [],
        "retry_queue": [],
        "failed": [],
        "source_urls": {"article.md": "https://example.com/article"},
    }
    assert state["source_urls"]["article.md"] == "https://example.com/article"


def test_rag_result_structure():
    """RagResult can be constructed with all required keys."""
    item: RagResult = {
        "content": "some content",
        "score": 0.85,
        "chunk_index": 0,
        "metadata": {"source": "doc.md"},
    }
    assert item["score"] == 0.85


def test_second_brain_state_structure():
    """SecondBrainState can be constructed with all required keys."""
    state: SecondBrainState = {
        "session_id": "abc-123",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    assert state["routing_decision"] == "neither"
