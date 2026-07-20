from second_brain.services.pii import redact_pii


def test_redact_person_name():
    result = redact_pii("Hello, my name is John Smith.")
    assert "[NAME]" in result
    assert "John Smith" not in result


def test_redact_email():
    result = redact_pii("Contact me at alice@example.com for details.")
    assert "[EMAIL]" in result
    assert "alice@example.com" not in result


def test_redact_phone_number():
    result = redact_pii("Call me at 555-867-5309 anytime.")
    assert "[PHONE]" in result
    assert "867-5309" not in result


def test_no_pii_passthrough():
    text = "The weather in Tokyo is sunny today."
    result = redact_pii(text)
    # Non-PII text must not be mangled
    assert "weather" in result
    assert "sunny" in result


def test_multiple_pii_types_in_one_string():
    text = "Jane Doe's email is jane.doe@corp.com and her phone is +1-800-555-0199."
    result = redact_pii(text)
    assert "Jane Doe" not in result
    assert "jane.doe@corp.com" not in result
    assert "[NAME]" in result
    assert "[EMAIL]" in result


def test_empty_string():
    result = redact_pii("")
    assert result == ""


def test_credit_card_redaction():
    result = redact_pii("My card number is 4111111111111111.")
    assert "4111111111111111" not in result
    assert "[CARD]" in result
