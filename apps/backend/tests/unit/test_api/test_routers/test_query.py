# apps/backend/tests/unit/test_api/test_routers/test_query.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from second_brain.api.routers.query import router as query_router

# The query router is not yet registered on second_brain.main.app (that wiring
# is Task 11's job) — build a standalone app here so this router can be
# exercised in isolation.
app = FastAPI()
app.include_router(query_router)


def _mock_final_state(**overrides):
    state = {
        "final_answer": "The answer is 42.",
        "confidence": 0.88,
        "is_uncertain": False,
        "conflict_context": [],
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_query_with_null_session_id_generates_new_thread_id():
    """sessionId=null must generate a new UUID7 and use it as the thread_id."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value=_mock_final_state())

    with patch(
        "second_brain.api.routers.query._get_graph",
        AsyncMock(return_value=mock_graph),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/query", json={"message": "Hello", "sessionId": None}
            )

    assert response.status_code == 200
    data = response.json()
    returned_session_id = data["sessionId"]
    assert returned_session_id  # non-empty, a new UUID7 was generated

    call_kwargs = mock_graph.ainvoke.call_args.kwargs
    assert call_kwargs["config"] == {"configurable": {"thread_id": returned_session_id}}


@pytest.mark.asyncio
async def test_query_with_existing_session_id_reuses_thread_id():
    """sessionId=<uuid> must be reused as-is for the thread_id."""
    existing_session_id = "01900000-0000-7000-8000-000000000001"
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value=_mock_final_state())

    with patch(
        "second_brain.api.routers.query._get_graph",
        AsyncMock(return_value=mock_graph),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/query",
                json={"message": "Hello again", "sessionId": existing_session_id},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["sessionId"] == existing_session_id

    call_kwargs = mock_graph.ainvoke.call_args.kwargs
    assert call_kwargs["config"] == {"configurable": {"thread_id": existing_session_id}}


@pytest.mark.asyncio
async def test_query_response_maps_graph_state_to_response_shape():
    """final_answer->answer, is_uncertain->isUncertain, confidence passthrough."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        return_value=_mock_final_state(
            final_answer="The answer is 42.",
            confidence=0.88,
            is_uncertain=False,
            conflict_context=[],
        )
    )

    with patch(
        "second_brain.api.routers.query._get_graph",
        AsyncMock(return_value=mock_graph),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/query", json={"message": "Hello"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "The answer is 42."
    assert data["confidence"] == 0.88
    assert data["isUncertain"] is False
    assert data["conflictDetected"] is False
    assert data["conflictContext"] == []


@pytest.mark.asyncio
async def test_query_response_reports_conflict_detected_when_conflict_context_present():
    """Non-empty conflict_context -> conflictDetected=True in the response."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        return_value=_mock_final_state(
            final_answer="Partial answer.",
            confidence=0.4,
            is_uncertain=True,
            conflict_context=["Existing fact says X, new statement says Y"],
        )
    )

    with patch(
        "second_brain.api.routers.query._get_graph",
        AsyncMock(return_value=mock_graph),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/query", json={"message": "Hello"})

    assert response.status_code == 200
    data = response.json()
    assert data["conflictDetected"] is True
    assert data["conflictContext"] == ["Existing fact says X, new statement says Y"]
    assert data["isUncertain"] is True


@pytest.mark.asyncio
async def test_query_graph_error_does_not_leak_exception_detail_to_client():
    """A graph failure must return 500 without echoing the raw exception
    (which may embed the Postgres DSN, including credentials) to the client."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        side_effect=Exception(
            "connection to postgresql://user:supersecret@host failed"
        )
    )

    with patch(
        "second_brain.api.routers.query._get_graph",
        AsyncMock(return_value=mock_graph),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/query", json={"message": "Hello"})

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "supersecret" not in detail
    assert "postgresql://" not in detail
