"""Integration test for the full document ingestion pipeline.

Requirements:
    - PostgreSQL running (docker compose up -d app_postgres)
    - Alembic migrations applied (alembic upgrade head)
    - Ollama and Anthropic are mocked — no live API keys required.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, delete, select

from second_brain.db.models import DocumentChunk, IngestedDocument
from second_brain.db.session import engine
from second_brain.graphs.state import IngestionState

FAKE_EMBEDDING = [0.01] * 1024
FAKE_HEADER = (
  "This chunk is from test-note.md, section Test Note, covering integration testing."
)


@pytest.fixture()
def tmp_dirs(tmp_path):
  """Create temp/pending-digest-docs, temp/processed, temp/failed directories."""
  pending = tmp_path / "pending-digest-docs"
  pending.mkdir()
  processed = tmp_path / "processed"
  processed.mkdir()
  failed = tmp_path / "failed"
  failed.mkdir()
  return {"pending": pending, "processed": processed, "failed": failed}


@pytest.fixture(autouse=True)
def clean_db():
  """Remove test records to avoid cross-test contamination."""
  yield
  with Session(engine) as session:
    session.exec(
      delete(DocumentChunk).where(
        DocumentChunk.doc_id.in_(
          select(IngestedDocument.id).where(IngestedDocument.filename.like("test-%"))
        )
      )
    )
    session.exec(
      delete(IngestedDocument).where(IngestedDocument.filename.like("test-%"))
    )
    session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_ingest_file_success(tmp_dirs):
  """A .md file in pending-digest-docs/ is fully processed and moved to processed/."""
  test_file = tmp_dirs["pending"] / "test-note.md"
  test_file.write_text(
    "# Test Note\n\nThis document covers integration testing.\n\n"
    "## Details\n\nMore detail content here for verification.\n"
  )

  node = "second_brain.nodes.ingestion_agent"
  with (
    patch(f"{node}.PENDING_DOCS_DIR", tmp_dirs["pending"]),
    patch(f"{node}.PROCESSED_DIR", tmp_dirs["processed"]),
    patch(f"{node}.FAILED_DIR", tmp_dirs["failed"]),
    patch(f"{node}.embed_text", AsyncMock(return_value=FAKE_EMBEDDING)),
    patch(
      f"{node}._generate_contextual_header",
      AsyncMock(return_value=FAKE_HEADER),
    ),
  ):
    from second_brain.graphs.ingestion_graph import build_ingestion_graph

    graph = build_ingestion_graph()

    initial: IngestionState = {
      "files": ["test-note.md"],
      "in_progress": None,
      "processed": [],
      "retry_queue": [],
      "failed": [],
    }
    final = await graph.ainvoke(initial)

  assert "test-note.md" in final["processed"], f"processed={final['processed']}"
  assert final["failed"] == []
  assert final["in_progress"] is None

  processed_file = tmp_dirs["processed"] / "test-note.md"
  pending_file = tmp_dirs["pending"] / "test-note.md"
  assert processed_file.exists(), "File must move to processed/"
  assert not pending_file.exists(), "File must not remain in pending/"

  with Session(engine) as session:
    doc = session.exec(
      select(IngestedDocument).where(IngestedDocument.filename == "test-note.md")
    ).first()
    assert doc is not None, "IngestedDocument record must be created"
    assert doc.status == "processed"
    assert doc.content_hash is not None

    chunks = session.exec(
      select(DocumentChunk).where(DocumentChunk.doc_id == doc.id)
    ).all()
    assert len(chunks) >= 1, "At least one DocumentChunk must be created"
    for chunk in chunks:
      assert len(chunk.embedding) == 1024, "Embedding must be 1024-dimensional"
      assert chunk.content, "Chunk content must not be empty"
      assert FAKE_HEADER in chunk.content, "Contextual header must be prepended"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_duplicate_file_is_skipped_on_reingest(tmp_dirs):
  """Re-ingesting the same file (same MD5) must not create duplicate DB records."""
  test_file = tmp_dirs["pending"] / "test-dupe.md"
  content = "# Dupe Test\n\nThis content is identical.\n"
  test_file.write_text(content)

  node = "second_brain.nodes.ingestion_agent"
  with (
    patch(f"{node}.PENDING_DOCS_DIR", tmp_dirs["pending"]),
    patch(f"{node}.PROCESSED_DIR", tmp_dirs["processed"]),
    patch(f"{node}.FAILED_DIR", tmp_dirs["failed"]),
    patch(f"{node}.embed_text", AsyncMock(return_value=FAKE_EMBEDDING)),
    patch(
      f"{node}._generate_contextual_header",
      AsyncMock(return_value=FAKE_HEADER),
    ),
  ):
    from second_brain.graphs.ingestion_graph import build_ingestion_graph

    graph = build_ingestion_graph()
    initial: IngestionState = {
      "files": ["test-dupe.md"],
      "in_progress": None,
      "processed": [],
      "retry_queue": [],
      "failed": [],
    }

    # First ingest
    await graph.ainvoke(initial)

    # Put file back in pending for second ingest
    (tmp_dirs["processed"] / "test-dupe.md").rename(
      tmp_dirs["pending"] / "test-dupe.md"
    )

    # Second ingest — must skip embedding because content_hash matches
    with patch(f"{node}.embed_text", AsyncMock()) as mock_embed:
      await graph.ainvoke(initial)
      mock_embed.assert_not_called()

  with Session(engine) as session:
    docs = session.exec(
      select(IngestedDocument).where(IngestedDocument.filename == "test-dupe.md")
    ).all()
    assert len(docs) == 1, f"Expected 1 record, got {len(docs)}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_api_endpoint_ingest_file_returns_correct_response(tmp_dirs):
  """POST /ingest/file returns {numberOfFilePassed, failedFiles} correctly."""
  (tmp_dirs["pending"] / "test-api.md").write_text("# API Test\n\nTest content.\n")

  node = "second_brain.nodes.ingestion_agent"
  with (
    patch(f"{node}.PENDING_DOCS_DIR", tmp_dirs["pending"]),
    patch(f"{node}.PROCESSED_DIR", tmp_dirs["processed"]),
    patch(f"{node}.FAILED_DIR", tmp_dirs["failed"]),
    patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", tmp_dirs["pending"]),
    patch(f"{node}.embed_text", AsyncMock(return_value=FAKE_EMBEDDING)),
    patch(
      f"{node}._generate_contextual_header",
      AsyncMock(return_value=FAKE_HEADER),
    ),
  ):
    from httpx import ASGITransport, AsyncClient

    from second_brain.main import app

    async with AsyncClient(
      transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
      response = await client.post("/ingest/file")

  assert response.status_code == 200
  data = response.json()
  assert data["numberOfFilePassed"] == 1
  assert data["failedFiles"] == []
