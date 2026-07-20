from langchain_core.messages import HumanMessage

from second_brain.graphs.state import SecondBrainState
from second_brain.services.pii import redact_pii


def redact_inbound(state: SecondBrainState) -> dict:
    """Graph node: redact PII from the last (current) user message.

    Returns a dict with only the redacted last message. LangGraph's add_messages
    reducer will merge this into the checkpoint, replacing the last message content
    without touching the rest of the message history.
    """
    last_message = state["messages"][-1]
    redacted_content = redact_pii(last_message.content)
    redacted_message = HumanMessage(
        content=redacted_content,
        id=last_message.id,  # preserve message id so add_messages replaces in-place
    )
    return {"messages": [redacted_message]}


def redact_outbound(state: SecondBrainState) -> dict:
    """Graph node: redact PII from the final_answer before it is persisted."""
    return {"final_answer": redact_pii(state["final_answer"])}
