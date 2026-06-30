import json
import uuid
from unittest.mock import MagicMock

from generate_dataset import _strip_code_fences, generate_qa_pairs_for_document


class TestStripCodeFences:
    def test_plain_json_is_unchanged(self):
        text = '[{"question": "Q?", "expected_answer": "A", "difficulty": "easy"}]'
        assert _strip_code_fences(text) == text

    def test_strips_triple_backtick_json_fence(self):
        text = '```json\n[{"question": "Q?"}]\n```'
        result = _strip_code_fences(text)
        assert result.strip() == '[{"question": "Q?"}]'

    def test_strips_plain_triple_backtick_fence(self):
        text = '```\n[{"question": "Q?"}]\n```'
        result = _strip_code_fences(text)
        assert result.strip() == '[{"question": "Q?"}]'


class TestGenerateQAPairsForDocument:
    def _make_doc(self) -> dict:
        return {
            "doc_id": str(uuid.uuid4()),
            "filename": "intro.md",
            "chunk_ids": ["chunk-abc"],
            "full_content": "RAG stands for Retrieval-Augmented Generation.",
        }

    def _make_client(self, raw_json: str) -> MagicMock:
        content_block = MagicMock()
        content_block.text = raw_json
        message = MagicMock()
        message.content = [content_block]
        client = MagicMock()
        client.messages.create.return_value = message
        return client

    def test_returns_list_of_qa_pairs(self):
        raw = json.dumps(
            [
                {
                    "question": "What is RAG?",
                    "expected_answer": "RAG is Retrieval-Augmented Generation.",
                    "difficulty": "easy",
                },
                {
                    "question": "Why use RAG?",
                    "expected_answer": "To improve answer quality.",
                    "difficulty": "medium",
                },
            ]
        )
        client = self._make_client(raw)
        pairs = generate_qa_pairs_for_document(client, self._make_doc(), n=2)
        assert len(pairs) == 2

    def test_each_pair_has_required_fields(self):
        raw = json.dumps(
            [
                {
                    "question": "What is RAG?",
                    "expected_answer": "Retrieval-Augmented Generation.",
                    "difficulty": "easy",
                },
            ]
        )
        client = self._make_client(raw)
        pairs = generate_qa_pairs_for_document(client, self._make_doc(), n=1)
        pair = pairs[0]
        assert "id" in pair
        assert "question" in pair
        assert "expected_answer" in pair
        assert "source_document" in pair
        assert "source_chunk_ids" in pair
        assert "difficulty" in pair

    def test_source_document_is_filename(self):
        raw = json.dumps(
            [
                {"question": "Q?", "expected_answer": "A.", "difficulty": "hard"},
            ]
        )
        client = self._make_client(raw)
        doc = self._make_doc()
        pairs = generate_qa_pairs_for_document(client, doc, n=1)
        assert pairs[0]["source_document"] == "intro.md"

    def test_handles_code_fenced_response(self):
        raw_inner = json.dumps(
            [
                {"question": "Q?", "expected_answer": "A.", "difficulty": "easy"},
            ]
        )
        raw = f"```json\n{raw_inner}\n```"
        client = self._make_client(raw)
        pairs = generate_qa_pairs_for_document(client, self._make_doc(), n=1)
        assert len(pairs) == 1

    def test_missing_difficulty_defaults_to_medium(self):
        raw = json.dumps([{"question": "Q?", "expected_answer": "A."}])
        client = self._make_client(raw)
        pairs = generate_qa_pairs_for_document(client, self._make_doc(), n=1)
        assert pairs[0]["difficulty"] == "medium"

    def test_id_is_valid_uuid(self):
        raw = json.dumps(
            [
                {"question": "Q?", "expected_answer": "A.", "difficulty": "easy"},
            ]
        )
        client = self._make_client(raw)
        pairs = generate_qa_pairs_for_document(client, self._make_doc(), n=1)
        uuid.UUID(pairs[0]["id"])  # raises if invalid
