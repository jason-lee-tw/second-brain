# apps/backend/tests/unit/test_api/test_schemas.py
import pytest
from pydantic import ValidationError

from second_brain.api.schemas import (
    IngestFileResponse,
    IngestUrlRequest,
    QueryRequest,
    QueryResponse,
)


def test_ingest_file_response_valid():
    resp = IngestFileResponse(numberOfFilePassed=5, failedFiles=["bad.md"])
    assert resp.numberOfFilePassed == 5
    assert resp.failedFiles == ["bad.md"]


def test_ingest_file_response_serializes_to_camel_case_keys():
    resp = IngestFileResponse(numberOfFilePassed=2, failedFiles=[])
    data = resp.model_dump()
    assert "numberOfFilePassed" in data
    assert "failedFiles" in data


def test_ingest_file_response_defaults_empty_failed_files():
    resp = IngestFileResponse(numberOfFilePassed=0, failedFiles=[])
    assert resp.failedFiles == []


def test_ingest_url_request_valid():
    req = IngestUrlRequest(urls=["https://example.com", "https://other.com"])
    assert len(req.urls) == 2
    assert "example.com" in str(req.urls[0])


def test_ingest_url_request_rejects_missing_urls():
    with pytest.raises(ValidationError):
        IngestUrlRequest()  # urls is required


def test_ingest_url_request_rejects_non_url_string():
    """A bare non-URL string must fail Pydantic validation with a 422-style error."""
    with pytest.raises(ValidationError):
        IngestUrlRequest(urls=["not-a-url"])


def test_query_request_with_null_session_id():
    req = QueryRequest(message="Hello", sessionId=None)
    assert req.message == "Hello"
    assert req.sessionId is None


def test_query_request_with_session_id():
    req = QueryRequest(
        message="Hello", sessionId="01900000-0000-7000-8000-000000000001"
    )
    assert req.sessionId == "01900000-0000-7000-8000-000000000001"


def test_query_request_session_id_defaults_to_none():
    req = QueryRequest(message="Hello")
    assert req.sessionId is None


def test_query_response_shape():
    resp = QueryResponse(
        answer="The answer is 42.",
        sessionId="01900000-0000-7000-8000-000000000001",
        confidence=0.88,
        isUncertain=False,
        conflictDetected=False,
        conflictContext=[],
    )
    assert resp.answer == "The answer is 42."
    assert resp.isUncertain is False
    assert resp.conflictDetected is False


def test_query_response_with_conflict_context():
    resp = QueryResponse(
        answer="Partial answer.",
        sessionId="01900000-0000-7000-8000-000000000001",
        confidence=0.4,
        isUncertain=True,
        conflictDetected=True,
        conflictContext=["Existing fact says X, new statement says Y"],
    )
    assert resp.conflictDetected is True
    assert resp.conflictContext == ["Existing fact says X, new statement says Y"]
