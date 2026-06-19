import httpx

from second_brain.config import settings

OLLAMA_BASE_URL = settings.ollama_base_url
EMBEDDING_MODEL = settings.embedding_model

_client = httpx.AsyncClient(timeout=60.0)


async def embed_text(text: str) -> list[float]:
    """Embed text via Ollama. Returns a 1024-dimensional float vector."""
    response = await _client.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": EMBEDDING_MODEL, "prompt": text},
    )
    response.raise_for_status()
    return response.json()["embedding"]
