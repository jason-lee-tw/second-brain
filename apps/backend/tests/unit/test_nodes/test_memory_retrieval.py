import pytest

from second_brain.nodes.memory_retrieval import retrieve_memory
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_retrieve_memory_stub_returns_empty_list():
    state = make_state()
    result = await retrieve_memory(state)
    assert result == {"retrieved_memory": []}
