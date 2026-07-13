from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from second_brain.graphs.state import IngestionState
from second_brain.nodes.ingestion_agent import ingestion_agent_node
from second_brain.nodes.pick_file import pick_file_node


def _route_after_ingest(state: IngestionState) -> str:
  """Continue looping if there are more files or retries; else terminate."""
  if state["files"] or state["retry_queue"]:
    return "pick_file"
  return END


def build_ingestion_graph() -> CompiledStateGraph[
  IngestionState, None, IngestionState, IngestionState
]:
  builder = StateGraph(IngestionState)

  builder.add_node("pick_file", pick_file_node)
  builder.add_node("ingest", ingestion_agent_node)

  builder.set_entry_point("pick_file")
  builder.add_edge("pick_file", "ingest")
  builder.add_conditional_edges("ingest", _route_after_ingest)

  return builder.compile()


# Module-level singleton used by the API router
ingestion_graph = build_ingestion_graph()
