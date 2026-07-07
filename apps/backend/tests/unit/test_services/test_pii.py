"""Unit tests for the PII redaction service."""

from second_brain.services.pii import redact_pii


def test_redact_person_name() -> None:
  result = redact_pii("My name is John Smith.")
  assert "[NAME]" in result
  assert "John Smith" not in result


def test_redact_email() -> None:
  result = redact_pii("Contact me at alice@example.com for details.")
  assert "[EMAIL]" in result
  assert "alice@example.com" not in result


def test_redact_phone() -> None:
  result = redact_pii("Call me at 212-555-1234.")
  assert "[PHONE]" in result
  assert "212-555-1234" not in result


def test_no_pii_passthrough() -> None:
  text = "The sky is blue and the sun is bright."
  result = redact_pii(text)
  assert result == text


def test_multiple_pii_types() -> None:
  text = "Jane Doe can be reached at jane.doe@example.com or 415-555-9876."
  result = redact_pii(text)
  assert "Jane Doe" not in result
  assert "jane.doe@example.com" not in result
  assert "415-555-9876" not in result
  assert "[NAME]" in result or "[EMAIL]" in result or "[PHONE]" in result


def test_empty_string() -> None:
  result = redact_pii("")
  assert result == ""


def test_redact_credit_card() -> None:
  result = redact_pii("My card number is 4111 1111 1111 1111.")
  assert "[CARD]" in result
  assert "4111 1111 1111 1111" not in result
