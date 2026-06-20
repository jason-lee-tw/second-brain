"""Unit tests for the MemoryRetrievalNode stub."""

import pytest

from second_brain.nodes.memory_retrieval import retrieve_memory
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_retrieve_memory_stub_returns_empty_list():
    """Happy path: stub always returns an empty retrieved_memory list."""
    result = await retrieve_memory(make_state())
    assert result == {"retrieved_memory": []}


@pytest.mark.asyncio
async def test_retrieve_memory_stub_ignores_existing_memory():
    """Edge case: even if state has memory, stub returns empty list."""
    state = make_state(retrieved_memory=["some existing memory"])
    result = await retrieve_memory(state)
    assert result == {"retrieved_memory": []}


@pytest.mark.asyncio
async def test_retrieve_memory_stub_returns_dict_not_list():
    """Edge case: return value is a dict update, not a bare list."""
    result = await retrieve_memory(make_state())
    assert isinstance(result, dict)
    assert "retrieved_memory" in result
    assert isinstance(result["retrieved_memory"], list)
