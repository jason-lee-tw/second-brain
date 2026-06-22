# apps/backend/tests/unit/test_query_router.py
"""Schema tests for QueryRequest / QueryResponse and query endpoint behaviour."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from second_brain.api.schemas import QueryRequest, QueryResponse
from second_brain.main import app


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


_PATCH_TARGET = "second_brain.api.routers.query._get_graph"


def test_graph_error_propagates_as_500_without_leaking_detail():
    """graph.ainvoke raising returns 500 without leaking the internal message."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = RuntimeError("internal db connection failed")

    with patch(_PATCH_TARGET, new=AsyncMock(return_value=mock_graph)):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/query", json={"message": "Hello"})

    assert response.status_code == 500
    assert "internal db connection failed" not in response.text


def test_graph_error_propagates_not_swallowed():
    """graph.ainvoke raising is NOT swallowed — it reaches the ASGI layer."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = RuntimeError("boom")

    with patch(_PATCH_TARGET, new=AsyncMock(return_value=mock_graph)):
        client = TestClient(app, raise_server_exceptions=True)
        with pytest.raises(RuntimeError, match="boom"):
            client.post("/query", json={"message": "Hello"})
