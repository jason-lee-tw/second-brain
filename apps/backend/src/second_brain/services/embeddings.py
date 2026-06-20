import httpx

from second_brain.config import settings

_client = httpx.AsyncClient(timeout=60.0)


async def shutdown() -> None:
    """Close the httpx async client. Called from the FastAPI lifespan."""
    await _client.aclose()


async def embed_text(text: str) -> list[float]:
    """Embed text via Ollama. Returns a 1024-dimensional float vector."""
    response = await _client.post(
        f"{settings.ollama_base_url}/api/embeddings",
        json={"model": settings.embedding_model, "prompt": text},
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise ValueError(f"Ollama error: {data['error']}")
    if "embedding" not in data:
        raise ValueError(f"Ollama response missing 'embedding' key: {data}")
    return data["embedding"]
