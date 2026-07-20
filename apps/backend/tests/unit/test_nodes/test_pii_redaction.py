# apps/backend/tests/unit/test_nodes/test_pii_redaction.py
from langchain_core.messages import HumanMessage

from second_brain.nodes.pii_redaction import redact_inbound, redact_outbound
from tests.unit.conftest import make_state


def test_redact_inbound_replaces_pii_in_last_message():
    state = make_state(
        messages=[HumanMessage(content="Hi, I'm Alice Johnson at alice@test.com")]
    )
    result = redact_inbound(state)
    updated_content = result["messages"][-1].content
    assert "[NAME]" in updated_content
    assert "[EMAIL]" in updated_content
    assert "Alice Johnson" not in updated_content
    assert "alice@test.com" not in updated_content


def test_redact_inbound_preserves_earlier_messages():
    earlier = HumanMessage(content="What is Python?")
    current = HumanMessage(content="My name is Bob Smith.")
    state = make_state(messages=[earlier, current])
    result = redact_inbound(state)
    # The returned dict only contains the last message update
    # Earlier messages are preserved in the LangGraph checkpoint
    assert len(result["messages"]) == 1
    assert "[NAME]" in result["messages"][-1].content


def test_redact_inbound_no_pii_message_unchanged():
    state = make_state(
        messages=[HumanMessage(content="How do I sort a list in Python?")]
    )
    result = redact_inbound(state)
    # Content should not be mangled when there is no PII
    assert "sort a list in Python" in result["messages"][-1].content


def test_redact_outbound_replaces_pii_in_final_answer():
    state = make_state(
        final_answer="You should contact Dr. Sarah Connor at s.connor@clinic.com."
    )
    result = redact_outbound(state)
    assert "[NAME]" in result["final_answer"]
    assert "[EMAIL]" in result["final_answer"]
    assert "Sarah Connor" not in result["final_answer"]
    assert "s.connor@clinic.com" not in result["final_answer"]


def test_redact_outbound_empty_answer_unchanged():
    state = make_state(final_answer="")
    result = redact_outbound(state)
    assert result["final_answer"] == ""
