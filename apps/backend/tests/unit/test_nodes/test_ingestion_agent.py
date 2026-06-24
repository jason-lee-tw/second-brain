# apps/backend/tests/unit/test_nodes/test_ingestion_agent.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from second_brain.graphs.state import IngestionState


def _make_state(**overrides) -> IngestionState:
    base: IngestionState = {
        "files": [],
        "in_progress": None,
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }
    base.update(overrides)
    return base


def test_chunk_semaphore_is_bounded():
    """_CHUNK_SEMAPHORE must be bounded by _CHUNK_CONCURRENCY."""
    from second_brain.nodes.ingestion_agent import _CHUNK_CONCURRENCY, _CHUNK_SEMAPHORE

    assert isinstance(_CHUNK_SEMAPHORE, asyncio.Semaphore)
    assert _CHUNK_SEMAPHORE._value == _CHUNK_CONCURRENCY


@pytest.mark.asyncio
async def test_successful_ingest_moves_file_to_processed(tmp_path):
    """On successful ingest, filename moves from in_progress to processed."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    (pending / "note.md").write_text("# Note\n\nContent here.\n")

    fake_embedding = [0.0] * 1024

    fake_header = "This chunk is from note.md, section Note, covering content."
    with (
        patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending),
        patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", processed),
        patch(
            "second_brain.nodes.ingestion_agent.embed_text",
            AsyncMock(return_value=fake_embedding),
        ),
        patch(
            "second_brain.nodes.ingestion_agent._generate_contextual_header",
            AsyncMock(return_value=fake_header),
        ),
        patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls,
        patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread,
    ):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None  # no duplicate
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node

        state = _make_state(in_progress="note.md")
        result = await ingestion_agent_node(state)

    assert "note.md" in result["processed"]
    assert result["in_progress"] is None
    assert (processed / "note.md").exists()
    assert mock_to_thread.call_count >= 2  # duplicate check + write results


@pytest.mark.asyncio
async def test_duplicate_file_is_skipped_and_moved_to_processed(tmp_path):
    """If content_hash matches an existing record, file is skipped (not re-embedded)."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    (pending / "dupe.md").write_text("# Dupe\n\nSame content.\n")

    with (
        patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending),
        patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", processed),
        patch(
            "second_brain.nodes.ingestion_agent.embed_text", AsyncMock()
        ) as mock_embed,
        patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # Simulate duplicate: exec().first() returns an existing record
        mock_session.exec.return_value.first.return_value = MagicMock()
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node

        state = _make_state(in_progress="dupe.md")
        result = await ingestion_agent_node(state)

    mock_embed.assert_not_called()
    assert "dupe.md" in result["processed"]
    assert (processed / "dupe.md").exists()


@pytest.mark.asyncio
async def test_first_failure_goes_to_retry_queue(tmp_path):
    """First failure increments retry_count to 1 and adds to retry_queue."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    (pending / "bad.md").write_text("# Bad\n\nContent.\n")

    with (
        patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending),
        patch(
            "second_brain.nodes.ingestion_agent.embed_text",
            AsyncMock(side_effect=RuntimeError("Ollama down")),
        ),
        patch(
            "second_brain.nodes.ingestion_agent._generate_contextual_header",
            AsyncMock(return_value="header"),
        ),
        patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node

        state = _make_state(in_progress="bad.md")
        result = await ingestion_agent_node(state)

    assert result["in_progress"] is None
    retry_entries = [f for f in result["retry_queue"] if f["filename"] == "bad.md"]
    assert len(retry_entries) == 1
    assert retry_entries[0]["retry_count"] == 1
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_generate_contextual_header_raises_when_no_text_block():
    """_generate_contextual_header raises ValueError when response has no TextBlock."""
    mock_response = MagicMock()
    mock_response.content = []  # no TextBlock

    with patch(
        "second_brain.nodes.ingestion_agent._anthropic.messages.create",
        new=AsyncMock(return_value=mock_response),
    ):
        from second_brain.nodes.ingestion_agent import _generate_contextual_header

        with pytest.raises(ValueError, match="No TextBlock in Anthropic response"):
            await _generate_contextual_header(
                filename="doc.md",
                heading_path="Intro",
                chunk_content="Some content here.",
            )


@pytest.mark.asyncio
async def test_third_failure_moves_to_failed_and_moves_file(tmp_path):
    """After MAX_RETRIES (3) failures, file moves to failed state and failed/ dir."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    (pending / "broken.md").write_text("# Broken\n\nContent.\n")

    with (
        patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending),
        patch("second_brain.nodes.ingestion_agent.FAILED_DIR", failed_dir),
        patch(
            "second_brain.nodes.ingestion_agent.embed_text",
            AsyncMock(side_effect=RuntimeError("permanent error")),
        ),
        patch(
            "second_brain.nodes.ingestion_agent._generate_contextual_header",
            AsyncMock(return_value="header"),
        ),
        patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node

        # Simulate already at retry_count=2 (next failure hits limit of 3)
        state = _make_state(
            in_progress="broken.md",
            retry_queue=[{"filename": "broken.md", "error": "err", "retry_count": 2}],
        )
        result = await ingestion_agent_node(state)

    assert result["in_progress"] is None
    assert result["retry_queue"] == []
    failed_entries = [f for f in result["failed"] if f["filename"] == "broken.md"]
    assert len(failed_entries) == 1
    assert failed_entries[0]["retry_count"] == 3
    assert (failed_dir / "broken.md").exists()
