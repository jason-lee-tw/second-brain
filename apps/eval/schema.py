import uuid
from typing import Literal, TypedDict

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
REQUIRED_FIELDS = {
    "id",
    "question",
    "expected_answer",
    "source_document",
    "source_chunk_ids",
    "difficulty",
}


class QAPair(TypedDict):
    id: str
    question: str
    expected_answer: str
    source_document: str
    source_chunk_ids: list[str]
    difficulty: Literal["easy", "medium", "hard"]


def validate_qa_pair(pair: dict) -> list[str]:
    """Return a list of validation error strings. Empty list means valid."""
    errors: list[str] = []

    missing = REQUIRED_FIELDS - set(pair.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
        return errors

    if not isinstance(pair["id"], str):
        errors.append("id must be a string")
    else:
        try:
            uuid.UUID(pair["id"])
        except ValueError:
            errors.append(f"id is not a valid UUID: {pair['id']!r}")

    if not isinstance(pair["question"], str) or not pair["question"].strip():
        errors.append("question must be a non-empty string")

    expected_answer = pair["expected_answer"]
    if not isinstance(expected_answer, str) or not expected_answer.strip():
        errors.append("expected_answer must be a non-empty string")

    source_document = pair["source_document"]
    if not isinstance(source_document, str) or not source_document.strip():
        errors.append("source_document must be a non-empty string")

    if not isinstance(pair["source_chunk_ids"], list):
        errors.append("source_chunk_ids must be a list of strings")

    if pair["difficulty"] not in VALID_DIFFICULTIES:
        got = repr(pair["difficulty"])
        errors.append(
            f"difficulty must be one of {sorted(VALID_DIFFICULTIES)}, got: {got}"
        )

    return errors


def validate_dataset(pairs: list[dict]) -> None:
    """Validate a list of Q&A pair dicts. Raises ValueError if any pair is invalid."""
    for i, pair in enumerate(pairs):
        errors = validate_qa_pair(pair)
        if errors:
            raise ValueError(f"Q&A pair at index {i} is invalid: {errors}")
