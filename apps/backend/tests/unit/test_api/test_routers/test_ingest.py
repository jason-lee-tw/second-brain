# apps/backend/tests/unit/test_api/test_routers/test_ingest.py
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from second_brain.main import app


@pytest.mark.asyncio
async def test_ingest_file_empty_directory_returns_zero_passed(tmp_path):
    """POST /ingest/file with no .md files returns numberOfFilePassed=0."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()

    with patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", pending):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    assert response.status_code == 200
    data = response.json()
    assert data["numberOfFilePassed"] == 0
    assert data["failedFiles"] == []


@pytest.mark.asyncio
async def test_ingest_file_invokes_graph_with_pending_files(tmp_path):
    """POST /ingest/file discovers .md files and invokes ingestion_graph."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    (pending / "doc1.md").write_text("content")
    (pending / "doc2.md").write_text("content")

    mock_final_state = {
        "processed": ["doc1.md", "doc2.md"],
        "failed": [],
        "files": [],
        "in_progress": [],
        "retry_queue": [],
    }

    with patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", pending), \
         patch("second_brain.api.routers.ingest.ingestion_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    assert response.status_code == 200
    data = response.json()
    assert data["numberOfFilePassed"] == 2
    assert data["failedFiles"] == []


@pytest.mark.asyncio
async def test_ingest_file_reports_failed_files(tmp_path):
    """POST /ingest/file returns failed filenames from final graph state."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    (pending / "bad.md").write_text("content")

    mock_final_state = {
        "processed": [],
        "failed": [{"filename": "bad.md", "error": "err", "retry_count": 3}],
        "files": [],
        "in_progress": [],
        "retry_queue": [],
    }

    with patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", pending), \
         patch("second_brain.api.routers.ingest.ingestion_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    data = response.json()
    assert data["numberOfFilePassed"] == 0
    assert "bad.md" in data["failedFiles"]


@pytest.mark.asyncio
async def test_ingest_url_crawls_and_invokes_graph():
    """POST /ingest/url crawls URLs via Tavily then invokes ingestion_graph."""
    mock_final_state = {
        "processed": ["example-com-page.md"],
        "failed": [],
        "files": [],
        "in_progress": [],
        "retry_queue": [],
    }

    fake_saved_path = Path("temp/pending-digest-docs/example-com-page.md")

    with patch("second_brain.api.routers.ingest.crawl_and_save",
               AsyncMock(return_value=fake_saved_path)) as mock_crawl, \
         patch("second_brain.api.routers.ingest.ingestion_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ingest/url",
                json={"urls": ["https://example.com/page"]},
            )

    assert response.status_code == 200
    mock_crawl.assert_called_once_with("https://example.com/page")
    data = response.json()
    assert data["numberOfFilePassed"] == 1
