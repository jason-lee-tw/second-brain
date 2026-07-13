# apps/backend/src/second_brain/nodes/orchestrator.py
from typing import Literal, override

from pydantic import BaseModel

from second_brain.graphs.state import RouteQueryOutput, SecondBrainState
from second_brain.nodes.base_node import BaseAgentNode
from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent
from second_brain.utils import get_str_content

_ROUTING_PROMPT = """\
You are a query router for a personal knowledge management system (Second Brain).

Given the user's query and any relevant memory context retrieved from long-term storage,
decide the best retrieval strategy:

  "rag"     — query asks about the user's personal notes, documents, or ingested
              knowledge
  "web"     — query requires current/real-time information from the internet
  "both"    — query benefits from both personal knowledge and web search
  "neither" — query is purely conversational and can be answered from context alone

User memory context (from long-term storage):
{memory_context}

User query: {query}

Choose the routing_decision that best serves the user."""


class _RoutingOutput(BaseModel):
  routing_decision: Literal["rag", "web", "both", "neither"]


class OrchestratorNode(BaseAgentNode[SecondBrainState, RouteQueryOutput]):
  """LLM-powered routing using claude-haiku-4-5."""

  def __init__(self):
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU))
    self._structured_llm = self._agent.get_model().with_structured_output(
      _RoutingOutput
    )

  @override
  async def __call__(self, state: SecondBrainState) -> RouteQueryOutput:
    """Reads messages[-1].content and retrieved_memory, outputs routing_decision."""
    query = get_str_content(state["messages"][-1])
    memory = state.get("retrieved_memory", [])
    memory_context = (
      "\n".join(f"- {m['fact']}" for m in memory)
      if memory
      else "No memory context available."
    )
    prompt = _ROUTING_PROMPT.format(memory_context=memory_context, query=query)
    result: _RoutingOutput = await self._structured_llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]
    return {"routing_decision": result.routing_decision}


route_query = OrchestratorNode()
