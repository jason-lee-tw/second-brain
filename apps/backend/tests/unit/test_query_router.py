# apps/backend/tests/unit/test_query_router.py
"""Schema tests for QueryRequest / QueryResponse."""

from second_brain.api.schemas import QueryRequest, QueryResponse


def test_query_request_with_null_session_id():
    """sessionId should default to None when omitted."""
    req = QueryRequest(message="Hello")
    assert req.message == "Hello"
    assert req.sessionId is None


def test_query_request_with_session_id():
    """sessionId is preserved when explicitly provided."""
    req = QueryRequest(message="Hello", sessionId="my-session-123")
    assert req.sessionId == "my-session-123"


def test_query_response_shape():
    """QueryResponse must accept all required fields and expose them correctly."""
    resp = QueryResponse(
        answer="42",
        sessionId="session-abc",
        confidence=0.95,
        isUncertain=False,
        conflictDetected=False,
        conflictContext=[],
    )
    assert resp.answer == "42"
    assert resp.sessionId == "session-abc"
    assert resp.confidence == 0.95
    assert resp.isUncertain is False
    assert resp.conflictDetected is False
    assert resp.conflictContext == []
