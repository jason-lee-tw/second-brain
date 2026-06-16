from fastapi.testclient import TestClient

from second_brain.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_ok_body():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}


def test_health_post_returns_405():
    response = client.post("/health")
    assert response.status_code == 405


def test_health_returns_json_content_type():
    response = client.get("/health")
    assert response.headers["content-type"].startswith("application/json")
