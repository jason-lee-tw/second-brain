from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from psycopg_pool import AsyncConnectionPool

from second_brain.graphs.state import SecondBrainState
from second_brain.nodes.memory_retrieval import retrieve_memory
from second_brain.nodes.orchestrator import route_query
from second_brain.nodes.pii_redaction import redact_inbound, redact_outbound
from second_brain.nodes.rag_retrieval import retrieve_from_rag
from second_brain.nodes.synthesis import synthesize_answer
from second_brain.nodes.web_research import search_web


def _route_retrieval(state: SecondBrainState):
    """Conditional edge: fan-out based on orchestrator routing_decision.

    Returns:
      - list[Send] for "rag", "web", "both" — parallel or single branch
      - "synthesis" string for "neither" — routes directly, skipping retrieval
    """
    decision = state["routing_decision"]
    if decision == "both":
        return [Send("rag_retrieval", state), Send("web_research", state)]
    elif decision == "rag":
        return [Send("rag_retrieval", state)]
    elif decision == "web":
        return [Send("web_research", state)]
    else:  # "neither"
        return "synthesis"


async def build_query_graph(postgres_url: str):
    """Build and compile the SecondBrain query graph with PostgresSaver checkpointing.

    threadId = session_id. Each session maintains its own conversation checkpoint
    so messages accumulate across turns (via add_messages reducer on SecondBrainState).

    Call once at app startup; the returned compiled graph is thread-safe for
    concurrent use.
    """
    pool = AsyncConnectionPool(
        conninfo=postgres_url, open=False, kwargs={"autocommit": True}
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()  # creates LangGraph checkpoint tables if absent

    workflow = StateGraph(SecondBrainState)

    # Register nodes
    workflow.add_node("redact_inbound", redact_inbound)
    workflow.add_node("retrieve_memory", retrieve_memory)
    workflow.add_node("orchestrator", route_query)
    workflow.add_node("rag_retrieval", retrieve_from_rag)
    workflow.add_node("web_research", search_web)
    workflow.add_node("synthesis", synthesize_answer)
    workflow.add_node("redact_outbound", redact_outbound)

    # Linear flow
    workflow.set_entry_point("redact_inbound")
    workflow.add_edge("redact_inbound", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "orchestrator")

    # Fan-out: orchestrator -> rag_retrieval and/or web_research (parallel via Send)
    # For "neither": routes directly to synthesis
    workflow.add_conditional_edges(
        "orchestrator",
        _route_retrieval,
        ["rag_retrieval", "web_research", "synthesis"],
    )

    # Both retrieval branches converge on synthesis
    workflow.add_edge("rag_retrieval", "synthesis")
    workflow.add_edge("web_research", "synthesis")

    # Final outbound PII scrub then done
    workflow.add_edge("synthesis", "redact_outbound")
    workflow.add_edge("redact_outbound", END)

    return workflow.compile(checkpointer=checkpointer)
