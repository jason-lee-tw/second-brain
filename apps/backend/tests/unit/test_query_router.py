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
    retrievedContexts=["Douglas Adams wrote The Hitchhiker's Guide."],
  )
  assert resp.answer == "42"
  assert resp.sessionId == "session-abc"
  assert resp.confidence == 0.95
  assert resp.isUncertain is False
  assert resp.conflictDetected is False
  assert resp.conflictContext == []
  assert resp.retrievedContexts == ["Douglas Adams wrote The Hitchhiker's Guide."]


def test_query_response_accepts_empty_retrieved_contexts():
  """retrievedContexts must round-trip as an empty list."""
  resp = QueryResponse(
    answer="42",
    sessionId="session-abc",
    confidence=0.95,
    isUncertain=False,
    conflictDetected=False,
    conflictContext=[],
    retrievedContexts=[],
  )
  assert resp.retrievedContexts == []


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


def _base_graph_result() -> dict:
  """Minimal SecondBrainState output dict satisfying the router's required keys."""
  return {
    "final_answer": "42",
    "confidence": 0.9,
    "is_uncertain": False,
  }


def test_retrieved_contexts_is_pass_through_of_context_used():
  """retrievedContexts is a straight pass-through of the graph's context_used —
  the single source of truth for what synthesis actually grounded the answer on."""
  mock_graph = AsyncMock()
  mock_graph.ainvoke.return_value = {
    **_base_graph_result(),
    "context_used": [
      "Paris is the capital of France.",
      "**Europe** (http://example.com)\nFrance is a country in Europe.",
      "- User is planning a trip to Paris. (confidence: 0.80)",
    ],
    "conflict_context": [],
  }

  with patch(_PATCH_TARGET, new=AsyncMock(return_value=mock_graph)):
    client = TestClient(app)
    response = client.post("/query", json={"message": "Tell me about Paris"})

  assert response.status_code == 200
  assert response.json()["retrievedContexts"] == [
    "Paris is the capital of France.",
    "**Europe** (http://example.com)\nFrance is a country in Europe.",
    "- User is planning a trip to Paris. (confidence: 0.80)",
  ]
