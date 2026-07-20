from langchain_core.messages import AIMessage, HumanMessage

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
    """Graph node: redact PII from the final_answer before it is persisted.

    This is the last node before END, and the only place the fully-redacted
    answer is known. The AIMessage appended to `messages` is built from the
    same redacted string as `final_answer` (computed once), so the two stay
    guaranteed-identical — no un-redacted PII is ever transiently persisted
    into the checkpointed message history.
    """
    redacted = redact_pii(state["final_answer"])
    return {"final_answer": redacted, "messages": [AIMessage(content=redacted)]}
