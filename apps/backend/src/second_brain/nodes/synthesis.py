from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from second_brain.config import settings
from second_brain.graphs.state import SecondBrainState

_SYNTHESIS_PROMPT = """\
You are a knowledgeable Second Brain assistant. Synthesize a comprehensive,
accurate answer from the available context. Be clear about what you know
and don't know.

--- Retrieved documents ---
{rag_context}

--- Web search results ---
{web_context}

--- Long-term memory ---
{memory_context}

--- Conversation history (last 10 turns) ---
{conversation_history}

--- Current question ---
{query}

Provide a helpful answer and rate your confidence from 0.0 (no idea) to 1.0 (certain).
Base confidence on the quality and relevance of the above context."""


class _SynthesisOutput(BaseModel):
    final_answer: str
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    reasoning: str


_UNCERTAINTY_THRESHOLD = 0.7
_NEITHER_CONFIDENCE_FLOOR = 0.5

_structured_llm = ChatAnthropic(
    model="claude-sonnet-4-6", anthropic_api_key=settings.anthropic_api_key
).with_structured_output(_SynthesisOutput)


def _format_messages(messages: list[BaseMessage]) -> str:
    parts = []
    for m in messages:
        role = "Human" if isinstance(m, HumanMessage) else "Assistant"
        parts.append(f"{role}: {m.content}")
    return "\n".join(parts) if parts else "(no prior conversation)"


async def synthesize_answer(state: SecondBrainState) -> dict:
    """Graph node: synthesize final answer using claude-sonnet-4-6.

    Combines rag_results + web_results + retrieved_memory + last 10 messages.
    Applies confidence floor of 0.5 when routing_decision == 'neither'.
    Sets is_uncertain=True when confidence < 0.7.
    """
    query = state["messages"][-1].content
    rag_results = state.get("rag_results", [])
    web_results = state.get("web_results", [])
    memory = state.get("retrieved_memory", [])
    routing = state.get("routing_decision", "neither")

    # Use last 10 messages, excluding the current query (which is the last one)
    history_messages = state["messages"][-10:-1]

    rag_context = (
        "\n\n".join(f"[Score: {r['score']:.2f}]\n{r['content']}" for r in rag_results)
        if rag_results
        else "No document context retrieved."
    )
    web_context = (
        "\n\n".join(f"[{r['title']}]({r['url']})\n{r['content']}" for r in web_results)
        if web_results
        else "No web results retrieved."
    )
    memory_context = (
        "\n".join(f"- {m['fact']}" for m in memory) if memory else "No memory context."
    )
    conversation_history = _format_messages(history_messages)

    prompt = _SYNTHESIS_PROMPT.format(
        rag_context=rag_context,
        web_context=web_context,
        memory_context=memory_context,
        conversation_history=conversation_history,
        query=query,
    )

    output: _SynthesisOutput = await _structured_llm.ainvoke(prompt)

    confidence = output.confidence
    # Apply floor for conversational turns where no external context was retrieved
    if routing == "neither":
        confidence = max(confidence, _NEITHER_CONFIDENCE_FLOOR)

    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }
