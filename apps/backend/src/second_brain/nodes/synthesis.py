"""Synthesis node: generates a final answer with confidence scoring."""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from second_brain.graphs.state import SecondBrainState, SynthesisNodeOutput

_UNCERTAINTY_THRESHOLD = 0.7
# "neither" route = no external retrieval attempted; assume baseline confidence
# since LLM answered from context alone
_NEITHER_CONFIDENCE_FLOOR = 0.5


class _SynthesisOutput(BaseModel):
    final_answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


_structured_llm = ChatAnthropic(model_name="claude-sonnet-4-6").with_structured_output(  # pyright: ignore[reportCallIssue]
    _SynthesisOutput
)


def _format_messages(messages: list[BaseMessage]) -> str:
    """Format a list of HumanMessage/AIMessage to a readable string."""
    parts = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            parts.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            parts.append(f"Assistant: {msg.content}")
        else:
            parts.append(f"[{type(msg).__name__}]: {msg.content}")
    return "\n".join(parts)


async def synthesize_answer(state: SecondBrainState) -> SynthesisNodeOutput:
    """LangGraph node: synthesize a final answer with confidence scoring."""
    query = state["messages"][-1].content
    routing = state.get("routing_decision", "neither")

    # Build context sections
    rag_context = ""
    if state.get("rag_results"):
        chunks = [r["content"] for r in state["rag_results"]]
        rag_context = "### RAG Context\n" + "\n---\n".join(chunks)

    web_context = ""
    if state.get("web_results"):
        items = [
            f"**{r['title']}** ({r['url']})\n{r['content']}"
            for r in state["web_results"]
        ]
        web_context = "### Web Research\n" + "\n---\n".join(items)

    memory_context = ""
    if state.get("retrieved_memory"):
        facts = [
            f"- {m['fact']} (confidence: {m['confidence']:.2f})"
            for m in state["retrieved_memory"]
        ]
        memory_context = "### Memory\n" + "\n".join(facts)

    # Use only the last 10 messages (excluding the current query) for history
    conversation_history = _format_messages(state["messages"][-11:-1])

    context_parts = [p for p in [rag_context, web_context, memory_context] if p]
    no_context = "No additional context available."
    context_section = "\n\n".join(context_parts) if context_parts else no_context

    prior_conv = (
        conversation_history if conversation_history else "No prior conversation."
    )
    prompt = (
        "You are a knowledgeable Second Brain assistant. "
        "Synthesize a clear, accurate answer.\n\n"
        f"## Current Query\n{query}\n\n"
        f"## Available Context\n{context_section}\n\n"
        f"## Conversation History\n{prior_conv}\n\n"
        "## Instructions\n"
        "- Provide a direct, helpful answer to the query.\n"
        "- Rate your confidence (0.0-1.0) based on available evidence.\n"
        "- Explain your reasoning briefly.\n"
        "- If context is limited, say so honestly and keep confidence lower.\n"
    )

    output: _SynthesisOutput = await _structured_llm.ainvoke(prompt)  # pyright: ignore[reportAssignmentType]

    confidence = output.confidence
    # Floor confidence for conversational queries: skipping external retrieval
    # means no uncertain sources were consulted
    if routing == "neither":
        confidence = max(confidence, _NEITHER_CONFIDENCE_FLOOR)

    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }
