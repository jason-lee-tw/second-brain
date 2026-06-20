from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_embed_text_returns_list_of_1024_floats():
    """embed_text must return a List[float] of length 1024."""
    fake_embedding = [0.1] * 1024
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": fake_embedding}
    mock_response.raise_for_status = MagicMock()

    with patch("second_brain.services.embeddings._client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)

        from second_brain.services.embeddings import embed_text

        result = await embed_text("hello world")

    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embed_text_posts_to_correct_endpoint_with_correct_payload():
    """embed_text must POST to /api/embeddings with model=qwen3-embedding:0.6b."""
    fake_embedding = [0.0] * 1024
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": fake_embedding}
    mock_response.raise_for_status = MagicMock()

    with patch("second_brain.services.embeddings._client") as mock_client:
        post_mock = AsyncMock(return_value=mock_response)
        mock_client.post = post_mock

        from second_brain.services.embeddings import embed_text

        await embed_text("test input")

    call_args = post_mock.call_args
    assert "/api/embeddings" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["model"] == "qwen3-embedding:0.6b"
    assert payload["prompt"] == "test input"


@pytest.mark.asyncio
async def test_embed_text_propagates_http_errors():
    """embed_text must not swallow HTTP errors."""
    with patch("second_brain.services.embeddings._client") as mock_client:
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=MagicMock()
            )
        )

        from second_brain.services.embeddings import embed_text

        with pytest.raises(httpx.HTTPStatusError):
            await embed_text("will fail")


@pytest.mark.asyncio
async def test_embed_text_raises_value_error_on_ollama_error_body():
    """embed_text must raise ValueError when Ollama returns HTTP 200 with error body."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"error": "model not found"}
    mock_response.raise_for_status = MagicMock()

    with patch("second_brain.services.embeddings._client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)

        from second_brain.services.embeddings import embed_text

        with pytest.raises(ValueError, match="model not found"):
            await embed_text("hello world")


@pytest.mark.asyncio
async def test_embed_text_raises_value_error_on_missing_embedding_key():
    """embed_text must raise ValueError when Ollama response has no 'embedding' key."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"model": "qwen3-embedding:0.6b"}
    mock_response.raise_for_status = MagicMock()

    with patch("second_brain.services.embeddings._client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)

        from second_brain.services.embeddings import embed_text

        with pytest.raises(ValueError, match="missing 'embedding' key"):
            await embed_text("hello world")
