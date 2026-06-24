"""MemoryRetrievalNode stub — full implementation in Ticket 5."""

from second_brain.graphs.state import RetrieveMemoryOutput, SecondBrainState


async def retrieve_memory(state: SecondBrainState) -> RetrieveMemoryOutput:  # pyright: ignore[reportUnusedParameter] — must be `state` not `_state`: pyright's structural check for StateNode requires the exact parameter name
    """Return an empty retrieved_memory list (stub; full impl in Ticket 5)."""
    return {"retrieved_memory": []}
