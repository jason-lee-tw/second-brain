from langgraph.graph import END, StateGraph

from second_brain.graphs.state import IngestionState
from second_brain.nodes.ingestion_agent import ingestion_agent_node


def pick_file_node(state: IngestionState) -> dict:
    """Move the next pending or retry file into in_progress.

    Priority: files[] (first-timers) before retry_queue.
    Does NOT remove the item from retry_queue — ingestion_agent_node does that
    after the attempt to preserve retry metadata for retry_count tracking.
    """
    if state["files"]:
        return {
            "files": state["files"][1:],
            "in_progress": state["files"][0],
        }
    if state["retry_queue"]:
        return {
            "in_progress": state["retry_queue"][0]["filename"],
        }
    return {"in_progress": None}


def _route_after_ingest(state: IngestionState) -> str:
    """Continue looping if there are more files or retries; else terminate."""
    if state["files"] or state["retry_queue"]:
        return "pick_file"
    return END


def build_ingestion_graph() -> StateGraph:
    builder = StateGraph(IngestionState)

    builder.add_node("pick_file", pick_file_node)
    builder.add_node("ingest", ingestion_agent_node)

    builder.set_entry_point("pick_file")
    builder.add_edge("pick_file", "ingest")
    builder.add_conditional_edges("ingest", _route_after_ingest)

    return builder.compile()


# Module-level singleton used by the API router
ingestion_graph = build_ingestion_graph()
