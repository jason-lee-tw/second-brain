"""PII redaction graph nodes for inbound queries and outbound answers."""

from langchain_core.messages import HumanMessage

from second_brain.graphs.state import SecondBrainState
from second_brain.services.pii import redact_pii


def redact_inbound(state: SecondBrainState) -> dict:
    """Redact PII from the last message before it enters the graph.

    Returns only the redacted message; the ``add_messages`` reducer replaces
    the existing message by id, preserving all prior messages.
    """
    if not state["messages"]:
        raise ValueError("redact_inbound requires at least one message in state")
    last = state["messages"][-1]
    redacted = HumanMessage(content=redact_pii(last.content), id=last.id)
    return {"messages": [redacted]}


def redact_outbound(state: SecondBrainState) -> dict:
    """Redact PII from the final answer before it leaves the graph."""
    return {"final_answer": redact_pii(state["final_answer"])}
