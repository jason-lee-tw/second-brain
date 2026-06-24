import uuid
from datetime import UTC, datetime

import pytest

from second_brain.db.models import (
    ChatHistory,
    DocumentChunk,
    IngestedDocument,
    LearnedFact,
    ModelCorrection,
)


class TestChatHistory:
    def test_instantiation(self):
        record = ChatHistory(
            session_id="01234567-0123-7000-8000-000000000000",
            thread_data={"messages": []},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert record.session_id == "01234567-0123-7000-8000-000000000000"
        assert record.thread_data == {"messages": []}

    def test_thread_data_defaults_to_empty_dict(self):
        record = ChatHistory(session_id="test-session-id")
        assert record.thread_data == {}


class TestIngestedDocument:
    def test_instantiation(self):
        doc_id = uuid.uuid4()
        record = IngestedDocument(
            id=doc_id,
            filename="notes.md",
            content_hash="d41d8cd98f00b204e9800998ecf8427e",
            status="processed",
            ingested_at=datetime.now(UTC),
        )
        assert record.id == doc_id
        assert record.filename == "notes.md"
        assert record.status == "processed"

    def test_source_url_is_optional(self):
        record = IngestedDocument(
            id=uuid.uuid4(),
            filename="local.md",
            content_hash="abc123",
            status="processed",
            ingested_at=datetime.now(UTC),
        )
        assert record.source_url is None


class TestDocumentChunk:
    def test_instantiation(self):
        record = DocumentChunk(
            id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            content="This chunk discusses Python basics.",
            embedding=[0.1] * 1024,
            chunk_index=0,
            chunk_metadata={
                "source": "notes.md",
                "heading_path": "Introduction",
                "content_type": "article",
                "char_count": 34,
            },
            created_at=datetime.now(UTC),
        )
        assert record.content == "This chunk discusses Python basics."
        assert len(record.embedding) == 1024
        assert record.chunk_index == 0

    def test_embedding_dimension(self):
        record = DocumentChunk(
            id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            content="text",
            embedding=[0.0] * 1024,
            chunk_index=1,
            created_at=datetime.now(UTC),
        )
        assert len(record.embedding) == 1024

    def test_chunk_metadata_defaults_to_none(self):
        record = DocumentChunk(
            id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            content="text",
            embedding=[0.0] * 1024,
            chunk_index=0,
            created_at=datetime.now(UTC),
        )
        assert record.chunk_metadata is None


class TestLearnedFact:
    def test_instantiation(self):
        record = LearnedFact(
            id=uuid.uuid4(),
            fact="The user prefers Python over Java",
            embedding=[0.2] * 1024,
            source_session="01234567-0123-7000-8000-000000000000",
            confidence=0.9,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert record.fact == "The user prefers Python over Java"
        assert record.confidence == 0.9

    def test_confidence_accepts_float(self):
        record = LearnedFact(
            id=uuid.uuid4(),
            fact="User works at Thoughtworks",
            embedding=[0.0] * 1024,
            source_session="some-session",
            confidence=0.75,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert record.confidence == pytest.approx(0.75)


class TestModelCorrection:
    def test_instantiation(self):
        record = ModelCorrection(
            id=uuid.uuid4(),
            original_answer="Python was created in 1990",
            correction="Python was created in 1991",
            root_cause="Off-by-one year error in training data",
            embedding=[0.3] * 1024,
            source_session="01234567-0123-7000-8000-000000000000",
            created_at=datetime.now(UTC),
        )
        assert record.original_answer == "Python was created in 1990"
        assert record.correction == "Python was created in 1991"
        assert record.root_cause == "Off-by-one year error in training data"

    def test_embedding_has_correct_dimension(self):
        # Embedding dimension is 1024. The invariant that embedding encodes `correction`
        # (not `original_answer`) is enforced in the persistence node, not here.
        record = ModelCorrection(
            id=uuid.uuid4(),
            original_answer="wrong answer",
            correction="right answer",
            root_cause="factual error",
            embedding=[0.5] * 1024,
            source_session="session-abc",
            created_at=datetime.now(UTC),
        )
        assert len(record.embedding) == 1024
