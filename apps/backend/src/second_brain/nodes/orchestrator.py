# apps/backend/src/second_brain/nodes/orchestrator.py
from typing import Literal

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from second_brain.graphs.state import RouteQueryOutput, SecondBrainState

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


_structured_llm = ChatAnthropic(model_name="claude-haiku-4-5").with_structured_output(
    _RoutingOutput
)


async def route_query(state: SecondBrainState) -> RouteQueryOutput:
    """Graph node: LLM-powered routing using claude-haiku-4-5.

    Reads messages[-1].content and retrieved_memory, outputs routing_decision.
    """
    query = state["messages"][-1].content
    memory = state.get("retrieved_memory", [])
    memory_context = (
        "\n".join(f"- {m['fact']}" for m in memory)
        if memory
        else "No memory context available."
    )
    prompt = _ROUTING_PROMPT.format(memory_context=memory_context, query=query)
    result: _RoutingOutput = await _structured_llm.ainvoke(prompt)  # type: ignore[assignment]
    return {"routing_decision": result.routing_decision}
