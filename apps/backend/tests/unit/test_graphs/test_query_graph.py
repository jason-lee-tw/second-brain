from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_build_query_graph_returns_compiled_graph():
    """Graph construction should succeed with a mocked checkpointer."""
    with (
        patch("second_brain.graphs.query_graph.AsyncConnectionPool") as MockPool,
        patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver,
    ):
        mock_pool_instance = MagicMock()
        mock_pool_instance.open = AsyncMock()
        MockPool.return_value = mock_pool_instance

        mock_saver_instance = MagicMock()
        mock_saver_instance.setup = AsyncMock()
        MockSaver.return_value = mock_saver_instance

        from second_brain.graphs.query_graph import build_query_graph

        graph = await build_query_graph("postgresql://fake:fake@localhost:5432/test")

    # Compiled graph must have an ainvoke method
    assert hasattr(graph, "ainvoke")
