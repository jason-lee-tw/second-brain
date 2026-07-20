# Task 6 Log: RAG Retrieval Node

## Task Context

### Plan Section
### Task 6: RAG Retrieval Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/rag_retrieval.py`
- Create: `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py`

**Dependencies:** `pip install asyncpg pgvector httpx`

**Assumption:** `settings.app_postgres_url` (e.g. `postgresql://user:pass@localhost:5432/second_brain`) and `settings.ollama_base_url` (e.g. `http://localhost:11434`) exist in `second_brain/core/config.py` from Ticket 1.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_rag_retrieval.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.rag_retrieval import retrieve_from_rag
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_returns_rag_results_list():
    state = make_state(messages=[HumanMessage(content="What is LangGraph?")])

    fake_rows = [
        {"content": "LangGraph is a library for building stateful agents.", "score": 0.92, "chunk_index": 0, "metadata": {"source": "langchain.md"}},
        {"content": "LangGraph uses StateGraph to manage state.", "score": 0.88, "chunk_index": 1, "metadata": {"source": "langchain.md"}},
    ]

    with patch("second_brain.nodes.rag_retrieval._embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock) as mock_db:
        mock_embed.return_value = [0.1] * 1024
        mock_db.return_value = fake_rows

        result = await retrieve_from_rag(state)

    assert "rag_results" in result
    assert len(result["rag_results"]) == 2
    assert result["rag_results"][0]["score"] == 0.92
    assert result["rag_results"][0]["chunk_index"] == 0
    assert result["rag_results"][0]["content"] == "LangGraph is a library for building stateful agents."


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    state = make_state(messages=[HumanMessage(content="What is the meaning of life?")])

    with patch("second_brain.nodes.rag_retrieval._embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock) as mock_db:
        mock_embed.return_value = [0.0] * 1024
        mock_db.return_value = []

        result = await retrieve_from_rag(state)

    assert result["rag_results"] == []


@pytest.mark.asyncio
async def test_embeds_last_message_content():
    """Verify the query used for embedding is messages[-1].content."""
    state = make_state(messages=[HumanMessage(content="Tell me about Python.")])
    captured_queries = []

    async def capture_embed(query, base_url):
        captured_queries.append(query)
        return [0.1] * 1024

    with patch("second_brain.nodes.rag_retrieval._embed_query", side_effect=capture_embed), \
         patch("second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = []
        await retrieve_from_rag(state)

    assert captured_queries == ["Tell me about Python."]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_rag_retrieval.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.rag_retrieval`.

- [ ] **Step 3: Implement the RAG retrieval node**

```python
# apps/backend/src/second_brain/nodes/rag_retrieval.py
import asyncpg
import httpx
from pgvector.asyncpg import register_vector

from second_brain.core.config import settings
from second_brain.graphs.state import RagResult, SecondBrainState


async def _embed_query(query: str, base_url: str) -> list[float]:
    """Call Ollama to embed the query using qwen3-embedding:0.6b (dim=1024)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/api/embeddings",
            json={"model": "qwen3-embedding:0.6b", "prompt": query},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def _query_pgvector(
    embedding: list[float], postgres_url: str, top_k: int = 5
) -> list[dict]:
    """Run cosine similarity search against document_chunks in pgvector."""
    conn = await asyncpg.connect(postgres_url)
    try:
        await register_vector(conn)
        rows = await conn.fetch(
            """
            SELECT content,
                   1 - (embedding <=> $1) AS score,
                   chunk_index,
                   metadata
            FROM document_chunks
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            embedding,
            top_k,
        )
        return [
            {
                "content": row["content"],
                "score": float(row["score"]),
                "chunk_index": row["chunk_index"],
                "metadata": dict(row["metadata"]) if row["metadata"] else {},
            }
            for row in rows
        ]
    finally:
        await conn.close()


async def retrieve_from_rag(state: SecondBrainState) -> dict:
    """Graph node: embed query via Ollama, cosine similarity search on document_chunks, top-k=5.

    Returns rag_results populated with RagResult items sorted by descending score.
    """
    query = state["messages"][-1].content
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding, settings.app_postgres_url)

    rag_results: list[RagResult] = [
        {
            "content": row["content"],
            "score": row["score"],
            "chunk_index": row["chunk_index"],
            "metadata": row["metadata"],
        }
        for row in rows
    ]
    return {"rag_results": rag_results}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_rag_retrieval.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/rag_retrieval.py \
  tests/unit/test_nodes/test_rag_retrieval.py
git commit -m "feat(nodes): add RAG retrieval node with pgvector cosine similarity"
```

---

## Attempt 1 — 2026-07-20T00:00:00Z

### Implementation Plan
- Write 3 failing tests adapted from the plan, mocking `second_brain.nodes.rag_retrieval.embed_text` (the shared embeddings service, not a locally-defined `_embed_query`) and a private `_query_pgvector` helper
- Run tests to confirm `ModuleNotFoundError` for `second_brain.nodes.rag_retrieval`
- Implement `retrieve_from_rag` reusing `embed_text` from `second_brain.services.embeddings`, plus a private `_query_pgvector` (asyncpg + `pgvector.asyncpg.register_vector`, cosine distance `<=>`, top-k=5) and a `_asyncpg_dsn` helper that strips the `+psycopg2` SQLAlchemy driver suffix from `settings.database_url`
- Run `just lint` and `just test-unit`, fix any lint line-length issues

### Files Changed
- created `apps/backend/src/second_brain/nodes/rag_retrieval.py` — RAG retrieval node: embeds query, queries pgvector, returns `rag_results`
- created `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py` — unit tests for `retrieve_from_rag`

### New Tests
- `test_returns_rag_results_list`
- `test_returns_empty_list_when_no_results`
- `test_embeds_last_message_content`

### Key Decisions
- Reused the shared `embed_text` from `second_brain.services.embeddings` instead of writing a local `_embed_query`/httpx client, per repo state note — avoids a second Ollama HTTP client and keeps embedding config (model name, timeout) in one place
- `settings.database_url` is a SQLAlchemy-dialect DSN (`postgresql+psycopg2://...`); added a small private `_asyncpg_dsn` one-liner in `rag_retrieval.py` (not in `config.py`) to strip `+psycopg2` before handing the DSN to `asyncpg.connect()`, avoiding conflicts with other parallel tasks touching shared config
- Kept `_query_pgvector` as a private, directly-mockable helper matching the plan's Step 1 test shape, rather than inlining the SQL into `retrieve_from_rag`

### Lint Output
PASS

### Test Output
PASS (97 passed, 3 new)

### Commit
`7390486`

### Outcome: success
