# apps/backend/tests/unit/test_graphs/test_state.py
from second_brain.graphs.state import FailedFile, IngestionState


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
