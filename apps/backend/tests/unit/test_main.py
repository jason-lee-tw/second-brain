"""Tests for FastAPI app lifespan — verifies client teardown on shutdown."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider

from second_brain.main import app, lifespan


@pytest.mark.asyncio
async def test_lifespan_closes_httpx_client():
  """Lifespan must call aclose() on the httpx AsyncClient after yield."""
  mock_client = AsyncMock()
  mock_provider = MagicMock(spec=TracerProvider)
  with (
    patch("second_brain.main.setup_tracing", return_value=mock_provider),
    patch("second_brain.services.embeddings._client", mock_client),
  ):
    async with lifespan(app):
      pass
  mock_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_closes_both_clients_even_if_one_raises():
  """If one teardown raises, the other must still run."""
  mock_client = AsyncMock()
  mock_client.aclose.side_effect = RuntimeError("httpx close failed")
  mock_shutdown_query_graph = AsyncMock()
  mock_provider = MagicMock(spec=TracerProvider)

  with (
    patch("second_brain.main.setup_tracing", return_value=mock_provider),
    patch("second_brain.services.embeddings._client", mock_client),
    patch("second_brain.main.shutdown_query_graph", mock_shutdown_query_graph),
  ):
    # Lifespan should not propagate teardown exceptions
    async with lifespan(app):
      pass

  mock_client.aclose.assert_called_once()
  mock_shutdown_query_graph.assert_called_once()
