"""MemoryRetrievalNode stub — full implementation in Ticket 5."""

from second_brain.graphs.state import RetrieveMemoryOutput, SecondBrainState


async def retrieve_memory(state: SecondBrainState) -> RetrieveMemoryOutput:  # pyright: ignore[reportUnusedParameter] — stub; keeping `state` (not `_state`) for consistency with all other node signatures
    """Return an empty retrieved_memory list (stub; full impl in Ticket 5)."""
    return {"retrieved_memory": []}
