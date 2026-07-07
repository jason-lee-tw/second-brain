"""Tests that all expected routes are registered in the FastAPI app."""

from fastapi.testclient import TestClient

from second_brain.main import app


def test_query_route_registered():
  """POST /query must be registered — 422 means route exists but validation failed."""
  client = TestClient(app, raise_server_exceptions=False)
  response = client.post("/query", json={})
  assert response.status_code != 404  # 422 = validation error = route exists
