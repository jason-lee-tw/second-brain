import uuid

import pytest
from schema import validate_dataset, validate_qa_pair


def _valid(**overrides) -> dict:
  base = {
    "id": str(uuid.uuid4()),
    "question": "What is RAG?",
    "expected_answer": "Retrieval-Augmented Generation.",
    "source_document": "intro.md",
    "source_chunk_ids": ["chunk-001"],
    "difficulty": "easy",
  }
  base.update(overrides)
  return base


class TestValidateQAPair:
  def test_valid_pair_returns_empty_error_list(self):
    assert validate_qa_pair(_valid()) == []

  def test_missing_question_returns_error(self):
    pair = _valid()
    del pair["question"]
    errors = validate_qa_pair(pair)
    assert any("question" in e for e in errors)

  def test_missing_expected_answer_returns_error(self):
    pair = _valid()
    del pair["expected_answer"]
    errors = validate_qa_pair(pair)
    assert any("expected_answer" in e for e in errors)

  def test_missing_id_returns_error(self):
    pair = _valid()
    del pair["id"]
    errors = validate_qa_pair(pair)
    assert errors

  def test_invalid_uuid_returns_error(self):
    errors = validate_qa_pair(_valid(id="not-a-uuid"))
    assert any("UUID" in e for e in errors)

  def test_empty_question_returns_error(self):
    errors = validate_qa_pair(_valid(question="   "))
    assert errors

  def test_empty_expected_answer_returns_error(self):
    errors = validate_qa_pair(_valid(expected_answer=""))
    assert errors

  def test_invalid_difficulty_returns_error(self):
    errors = validate_qa_pair(_valid(difficulty="super-hard"))
    assert any("difficulty" in e for e in errors)

  def test_easy_difficulty_is_valid(self):
    assert validate_qa_pair(_valid(difficulty="easy")) == []

  def test_medium_difficulty_is_valid(self):
    assert validate_qa_pair(_valid(difficulty="medium")) == []

  def test_hard_difficulty_is_valid(self):
    assert validate_qa_pair(_valid(difficulty="hard")) == []

  def test_source_chunk_ids_must_be_list(self):
    errors = validate_qa_pair(_valid(source_chunk_ids="chunk-1"))
    assert any("source_chunk_ids" in e for e in errors)

  def test_missing_source_document_returns_error(self):
    pair = _valid()
    del pair["source_document"]
    errors = validate_qa_pair(pair)
    assert any("source_document" in e for e in errors)


class TestValidateDataset:
  def test_valid_dataset_does_not_raise(self):
    dataset = [_valid() for _ in range(3)]
    validate_dataset(dataset)  # must not raise

  def test_invalid_pair_raises_value_error_with_index(self):
    dataset = [_valid(), _valid(difficulty="impossible"), _valid()]
    with pytest.raises(ValueError, match="index 1"):
      validate_dataset(dataset)

  def test_empty_dataset_does_not_raise(self):
    validate_dataset([])
