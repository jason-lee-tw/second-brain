# apps/backend/src/second_brain/graphs/query_graph.py
"""SecondBrain query LangGraph with PostgresSaver checkpointing."""

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from psycopg_pool import AsyncConnectionPool

from second_brain.graphs.state import SecondBrainState
from second_brain.nodes.memory_agent import memory_agent_node
from second_brain.nodes.memory_persistence import memory_persistence_node
from second_brain.nodes.memory_retrieval import memory_retrieval_node
from second_brain.nodes.orchestrator import route_query
from second_brain.nodes.pii_redaction import redact_inbound, redact_outbound
from second_brain.nodes.rag_retrieval import retrieve_from_rag
from second_brain.nodes.synthesis import synthesize_answer
from second_brain.nodes.web_research import search_web


def _route_retrieval(state: SecondBrainState) -> str | list[Send]:
    """Fan-out router: dispatches parallel retrieval or falls through to synthesis."""
    decision = state["routing_decision"]
    if decision == "both":
        return [Send("rag_retrieval", state), Send("web_research", state)]
    elif decision == "rag":
        return [Send("rag_retrieval", state)]
    elif decision == "web":
        return [Send("web_research", state)]
    else:
        return "synthesis"


async def build_query_graph(
    postgres_url: str,
) -> tuple[
    CompiledStateGraph[SecondBrainState, None, SecondBrainState, SecondBrainState],
    AsyncConnectionPool[Any],
]:
    """Build and compile the SecondBrain query graph with Postgres checkpointing.

    Args:
        postgres_url: A plain ``postgresql://`` connection string (no driver suffix).

    Returns:
        A ``(compiled_graph, pool)`` tuple — the caller is responsible for closing
        the pool on shutdown via ``await pool.close()``.
    """
    # autocommit=True: psycopg3 wraps connections in an implicit transaction by
    # default; AsyncPostgresSaver.setup() runs CREATE INDEX CONCURRENTLY, which
    # cannot execute inside a transaction block.
    pool = AsyncConnectionPool(
        conninfo=postgres_url, open=False, kwargs={"autocommit": True}
    )
    await pool.open()

    try:
        checkpointer = AsyncPostgresSaver(pool)  # pyright: ignore[reportArgumentType]
        await checkpointer.setup()
    except Exception:
        await pool.close()
        raise

    workflow = StateGraph(SecondBrainState)

    # Nodes
    workflow.add_node("redact_inbound", redact_inbound)
    workflow.add_node("memory_retrieval_node", memory_retrieval_node)
    workflow.add_node("memory_agent", memory_agent_node)
    workflow.add_node("memory_persistence", memory_persistence_node)
    workflow.add_node("orchestrator", route_query)
    workflow.add_node("rag_retrieval", retrieve_from_rag)
    workflow.add_node("web_research", search_web)
    workflow.add_node("synthesis", synthesize_answer)
    workflow.add_node("redact_outbound", redact_outbound)

    # Edges
    workflow.set_entry_point("redact_inbound")
    workflow.add_edge("redact_inbound", "memory_retrieval_node")
    workflow.add_edge("memory_retrieval_node", "orchestrator")
    workflow.add_conditional_edges(
        "orchestrator",
        _route_retrieval,
        ["rag_retrieval", "web_research", "synthesis"],
    )
    workflow.add_edge("rag_retrieval", "synthesis")
    workflow.add_edge("web_research", "synthesis")
    workflow.add_edge("synthesis", "redact_outbound")
    workflow.add_edge("redact_outbound", "memory_agent")
    workflow.add_edge("memory_agent", "memory_persistence")
    workflow.add_edge("memory_persistence", END)

    compiled = workflow.compile(checkpointer=checkpointer)
    return compiled, pool
