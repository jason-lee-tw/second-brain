"""Unit tests for PIIRedactionNode (inbound + outbound)."""

from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from tests.unit.conftest import make_state

# ---------------------------------------------------------------------------
# redact_inbound
# ---------------------------------------------------------------------------


def test_redact_inbound_scrubs_pii_in_last_message():
    """redact_inbound replaces PII content in the last message."""
    from second_brain.nodes.pii_redaction import redact_inbound

    state = make_state(
        messages=[HumanMessage(content="My email is john@example.com", id="msg-1")]
    )

    with patch(
        "second_brain.nodes.pii_redaction.redact_pii",
        return_value="My email is [EMAIL]",
    ) as mock_redact:
        result = redact_inbound(state)

    mock_redact.assert_called_once_with("My email is john@example.com")
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == "My email is [EMAIL]"
    assert result["messages"][0].id == "msg-1"


def test_redact_inbound_preserves_prior_messages():
    """redact_inbound returns only 1 message (last); prior kept via add_messages."""
    from second_brain.nodes.pii_redaction import redact_inbound

    prior = HumanMessage(content="Hello world", id="msg-0")
    last = HumanMessage(content="Call me at 555-1234", id="msg-1")
    state = make_state(messages=[prior, last])

    with patch(
        "second_brain.nodes.pii_redaction.redact_pii",
        return_value="Call me at [PHONE]",
    ):
        result = redact_inbound(state)

    # Only the last (redacted) message is returned; reducer merges by id
    assert len(result["messages"]) == 1
    assert result["messages"][0].id == "msg-1"
    assert result["messages"][0].content == "Call me at [PHONE]"


def test_redact_inbound_raises_on_empty_messages():
    """redact_inbound raises ValueError when messages list is empty."""
    from second_brain.nodes.pii_redaction import redact_inbound

    state = make_state(messages=[])
    with pytest.raises(
        ValueError, match="redact_inbound requires at least one message"
    ):
        redact_inbound(state)


def test_redact_inbound_no_pii_passthrough():
    """redact_inbound is a no-op when there is no PII in the last message."""
    from second_brain.nodes.pii_redaction import redact_inbound

    state = make_state(
        messages=[HumanMessage(content="What is the capital of France?", id="msg-2")]
    )

    with patch(
        "second_brain.nodes.pii_redaction.redact_pii",
        return_value="What is the capital of France?",
    ) as mock_redact:
        result = redact_inbound(state)

    mock_redact.assert_called_once()
    assert result["messages"][0].content == "What is the capital of France?"
    assert result["messages"][0].id == "msg-2"


# ---------------------------------------------------------------------------
# redact_outbound
# ---------------------------------------------------------------------------


def test_redact_outbound_scrubs_final_answer():
    """redact_outbound removes PII from final_answer."""
    from second_brain.nodes.pii_redaction import redact_outbound

    state = make_state(final_answer="The patient is Jane Doe, SSN 123-45-6789.")

    with patch(
        "second_brain.nodes.pii_redaction.redact_pii",
        return_value="The patient is [NAME], SSN [ID].",
    ) as mock_redact:
        result = redact_outbound(state)

    mock_redact.assert_called_once_with("The patient is Jane Doe, SSN 123-45-6789.")
    assert result["final_answer"] == "The patient is [NAME], SSN [ID]."


def test_redact_outbound_empty_final_answer_unchanged():
    """redact_outbound passes empty string through unchanged."""
    from second_brain.nodes.pii_redaction import redact_outbound

    state = make_state(final_answer="")

    with patch(
        "second_brain.nodes.pii_redaction.redact_pii", return_value=""
    ) as mock_redact:
        result = redact_outbound(state)

    mock_redact.assert_called_once_with("")
    assert result["final_answer"] == ""
