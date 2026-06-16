# Document Ingestion Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete document ingestion pipeline — hybrid chunking, Ollama embedding, pgvector storage, deduplication, retry logic, and both `/ingest/file` and `/ingest/url` endpoints.

**Architecture:** Files dropped in `temp/pending-digest-docs/` are processed by a LangGraph graph (`IngestionState`) that chunks documents using a hybrid strategy (headings → paragraphs → sentences), prepends LLM-generated contextual headers per chunk, embeds via Ollama `qwen3-embedding:0.6b`, and upserts to PostgreSQL pgvector. The graph retries failed files up to 3 total attempts, moving terminal failures to `temp/failed/` and successes to `temp/processed/`. URL ingestion first crawls via Tavily to save a markdown file, then feeds the same graph.

**Tech Stack:** Python, FastAPI, LangGraph, SQLModel, PostgreSQL + pgvector, Ollama (`qwen3-embedding:0.6b`), `claude-haiku-4-5` (contextual headers), `tavily-python`, `tiktoken` (cl100k_base), `httpx`

**Prerequisites:** Ticket 1 (infrastructure) complete — these files already exist:
- `apps/backend/src/second_brain/db/models.py` — `IngestedDocument`, `DocumentChunk` SQLModel models
- `apps/backend/src/second_brain/db/session.py` — `engine` SQLAlchemy engine
- `apps/backend/src/second_brain/main.py` — FastAPI `app` instance
- `apps/backend/pyproject.toml` or equivalent — `second_brain` package installable from `src/`

---

## File Map

| Status | Path | Responsibility |
|--------|------|----------------|
| Create | `apps/backend/src/second_brain/services/embeddings.py` | Ollama HTTP embed call |
| Create | `apps/backend/src/second_brain/services/chunking.py` | Hybrid chunker (Chunk dataclass, chunk_document) |
| Create | `apps/backend/src/second_brain/services/tavily.py` | Tavily URL crawl → markdown file |
| Create | `apps/backend/src/second_brain/graphs/state.py` | IngestionState, FailedFile TypedDicts |
| Create | `apps/backend/src/second_brain/nodes/ingestion_agent.py` | LangGraph node: read → dedup → chunk → header → embed → upsert |
| Create | `apps/backend/src/second_brain/graphs/ingestion_graph.py` | LangGraph graph: pick_file → ingest → route loop |
| Create | `apps/backend/src/second_brain/api/schemas.py` | IngestFileResponse, IngestUrlRequest Pydantic models |
| Create | `apps/backend/src/second_brain/api/routers/ingest.py` | POST /ingest/file and POST /ingest/url |
| Modify | `apps/backend/src/second_brain/main.py` | Register ingest router |
| Create | `apps/backend/tests/unit/test_services/test_embeddings.py` | Unit tests for embed_text |
| Create | `apps/backend/tests/unit/test_services/test_chunking.py` | Unit tests for chunk_document (all 3 content types + code fences) |
| Create | `apps/backend/tests/unit/test_services/test_tavily.py` | Unit tests for crawl_url, crawl_and_save |
| Create | `apps/backend/tests/unit/test_graphs/test_state.py` | Unit tests for TypedDict construction |
| Create | `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py` | Unit tests for ingestion_agent_node |
| Create | `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py` | Unit tests for graph routing/retry logic |
| Create | `apps/backend/tests/unit/test_api/test_schemas.py` | Unit tests for Pydantic schemas |
| Create | `apps/backend/tests/unit/test_api/test_routers/test_ingest.py` | Unit tests for ingest router endpoints |
| Create | `apps/backend/tests/integration/test_ingestion_graph.py` | End-to-end ingestion flow test |

All `pytest` commands below are run from `apps/backend/`.

---

### Task 1: Embedding Service

**Files:**
- Create: `apps/backend/src/second_brain/services/embeddings.py`
- Create: `apps/backend/tests/unit/test_services/test_embeddings.py`

- [ ] **Step 1: Create the test file with three failing tests**

```python
# apps/backend/tests/unit/test_services/test_embeddings.py
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_embed_text_returns_list_of_1024_floats():
    """embed_text must return a List[float] of length 1024."""
    fake_embedding = [0.1] * 1024
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": fake_embedding}
    mock_response.raise_for_status = MagicMock()

    with patch("second_brain.services.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

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

    with patch("second_brain.services.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        post_mock = AsyncMock(return_value=mock_response)
        mock_client.post = post_mock
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

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
    with patch("second_brain.services.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=MagicMock()
            )
        )
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        from second_brain.services.embeddings import embed_text
        with pytest.raises(httpx.HTTPStatusError):
            await embed_text("will fail")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_services/test_embeddings.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.services.embeddings'`

- [ ] **Step 3: Implement the embedding service**

```python
# apps/backend/src/second_brain/services/embeddings.py
import os
from typing import List

import httpx

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = "qwen3-embedding:0.6b"


async def embed_text(text: str) -> List[float]:
    """Embed text via Ollama. Returns a 1024-dimensional float vector."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
        )
        response.raise_for_status()
        return response.json()["embedding"]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_services/test_embeddings.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/services/embeddings.py \
        apps/backend/tests/unit/test_services/test_embeddings.py
git commit -m "feat(ingestion): add Ollama embedding service"
```

---

### Task 2: Hybrid Chunking Service

**Files:**
- Create: `apps/backend/src/second_brain/services/chunking.py`
- Create: `apps/backend/tests/unit/test_services/test_chunking.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_services/test_chunking.py
import pytest
from second_brain.services.chunking import (
    Chunk,
    chunk_document,
    detect_content_type,
)


# ── Content-type detection ─────────────────────────────────────────────────

def test_detect_article_when_h1_present():
    text = "# My Heading\n\nSome paragraph text here."
    assert detect_content_type(text) == "article"


def test_detect_article_when_h2_present():
    text = "Some intro.\n\n## Section\n\nBody text."
    assert detect_content_type(text) == "article"


def test_detect_transcription_when_no_headings():
    text = "Speaker A: Hello.\n\nSpeaker B: Hi there, how are you today?"
    assert detect_content_type(text) == "transcription"


# ── Chunk dataclass ────────────────────────────────────────────────────────

def test_chunk_document_returns_list_of_chunk_objects():
    content = "# Doc\n\nSome content here."
    chunks = chunk_document(content, source="doc.md")
    assert isinstance(chunks, list)
    assert all(isinstance(c, Chunk) for c in chunks)


# ── Heading path in metadata ───────────────────────────────────────────────

def test_chunk_metadata_contains_h1_heading_path():
    content = "# Introduction\n\nSome intro text.\n"
    chunks = chunk_document(content, source="doc.md")
    assert len(chunks) >= 1
    heading_paths = [c.metadata["heading_path"] for c in chunks]
    assert "Introduction" in heading_paths


def test_chunk_metadata_contains_nested_heading_path():
    content = (
        "# Introduction\n\nIntro content.\n\n"
        "## Background\n\nBackground content.\n\n"
        "### Details\n\nDetail content.\n"
    )
    chunks = chunk_document(content, source="doc.md")
    paths = {c.metadata["heading_path"] for c in chunks}
    assert "Introduction" in paths
    assert "Introduction > Background" in paths
    assert "Introduction > Background > Details" in paths


def test_chunk_metadata_resets_h3_when_new_h2_encountered():
    content = (
        "# Root\n\nRoot content.\n\n"
        "## First\n\n### Deep\n\nDeep content.\n\n"
        "## Second\n\nSecond content.\n"
    )
    chunks = chunk_document(content, source="doc.md")
    paths = {c.metadata["heading_path"] for c in chunks}
    # "Root > Second" must exist, not "Root > First > Deep > ..." bleeding into Second
    assert "Root > Second" in paths
    assert "Root > First > Deep" in paths


# ── Sequential chunk index ─────────────────────────────────────────────────

def test_chunk_indices_are_sequential_starting_at_zero():
    content = (
        "# A\n\nParagraph one.\n\n"
        "## B\n\nParagraph two.\n"
    )
    chunks = chunk_document(content, source="doc.md")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


# ── Metadata fields ────────────────────────────────────────────────────────

def test_chunk_metadata_contains_source_and_char_count():
    content = "# Doc\n\nContent here.\n"
    chunks = chunk_document(content, source="my-file.md")
    for chunk in chunks:
        assert chunk.metadata["source"] == "my-file.md"
        assert isinstance(chunk.metadata["char_count"], int)
        assert chunk.metadata["char_count"] > 0


def test_article_chunk_has_article_content_type():
    content = "# Article\n\nSome content.\n"
    chunks = chunk_document(content, source="article.md")
    assert all(c.metadata["content_type"] == "article" for c in chunks)


def test_transcription_chunk_has_transcription_content_type():
    content = "Speaker A: Hello.\n\nSpeaker B: How are you?"
    chunks = chunk_document(content, source="meeting.md")
    assert all(c.metadata["content_type"] == "transcription" for c in chunks)


# ── Code fence atomicity ───────────────────────────────────────────────────

def test_code_fence_never_split_across_chunks():
    """A code block must appear entirely within one chunk, never split."""
    content = (
        "# Tech Note\n\n"
        "Intro paragraph.\n\n"
        "```python\n"
        "def example():\n"
        "    x = 1\n"
        "    y = 2\n"
        "    return x + y\n"
        "```\n\n"
        "Conclusion paragraph.\n"
    )
    chunks = chunk_document(content, source="note.md")
    fence_chunks = [c for c in chunks if "```python" in c.content]
    assert len(fence_chunks) == 1, "Code fence must be entirely in exactly one chunk"
    assert "def example" in fence_chunks[0].content
    assert "return x + y" in fence_chunks[0].content


def test_multiple_code_fences_each_atomic():
    content = (
        "# Doc\n\n"
        "```bash\necho hello\n```\n\n"
        "Middle text.\n\n"
        "```python\nprint('hi')\n```\n"
    )
    chunks = chunk_document(content, source="doc.md")
    bash_chunks = [c for c in chunks if "echo hello" in c.content]
    python_chunks = [c for c in chunks if "print('hi')" in c.content]
    assert len(bash_chunks) == 1
    assert len(python_chunks) == 1


# ── Pre-heading content ────────────────────────────────────────────────────

def test_content_before_first_heading_is_captured():
    content = "Preamble text here.\n\n# Section\n\nSection content.\n"
    chunks = chunk_document(content, source="doc.md")
    all_content = " ".join(c.content for c in chunks)
    assert "Preamble text here" in all_content


# ── Empty / minimal inputs ─────────────────────────────────────────────────

def test_empty_content_returns_empty_list_or_single_empty_chunk():
    """Empty content should not crash; may return zero chunks."""
    chunks = chunk_document("", source="empty.md")
    # If a chunk is returned, its content should be empty or whitespace
    for c in chunks:
        assert c.content.strip() == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_services/test_chunking.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.services.chunking'`

- [ ] **Step 3: Implement the chunking service**

```python
# apps/backend/src/second_brain/services/chunking.py
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")

# Token budgets per content type
ARTICLE_TARGET = 512
ARTICLE_MAX = 1024
ARTICLE_OVERLAP = 64

TRANSCRIPTION_TARGET = 256
TRANSCRIPTION_MAX = 512
TRANSCRIPTION_OVERLAP = 0

MAX_RETRIES = 3  # total attempts before terminal failure


@dataclass
class Chunk:
    content: str
    chunk_index: int
    metadata: dict  # {source, heading_path, content_type, char_count}


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def detect_content_type(text: str) -> str:
    """Return 'article' if markdown H1/H2/H3 headings exist, else 'transcription'."""
    if re.search(r"^#{1,3}\s", text, re.MULTILINE):
        return "article"
    return "transcription"


def _extract_code_fences(text: str) -> Tuple[str, Dict[str, str]]:
    """Replace ``` code fences with unique placeholders to protect them from splitting."""
    placeholders: Dict[str, str] = {}
    counter = [0]

    def replacer(match: re.Match) -> str:
        key = f"__FENCE_{counter[0]}__"
        placeholders[key] = match.group(0)
        counter[0] += 1
        return key

    modified = re.sub(r"```[\s\S]*?```", replacer, text)
    return modified, placeholders


def _restore_fences(text: str, placeholders: Dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _split_by_headings(text: str) -> List[Tuple[str, str]]:
    """Split on H1/H2/H3 boundaries.

    Returns [(heading_path, body_text)] where heading_path is "H1 > H2 > H3".
    Content before the first heading gets an empty heading_path.
    """
    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))

    if not matches:
        stripped = text.strip()
        return [("", stripped)] if stripped else []

    sections: List[Tuple[str, str]] = []
    heading_stack: List[str] = ["", "", ""]  # index 0=H1, 1=H2, 2=H3

    # Capture content before the first heading
    pre = text[: matches[0].start()].strip()
    if pre:
        sections.append(("", pre))

    for i, match in enumerate(matches):
        level = len(match.group(1))          # 1, 2, or 3
        title = match.group(2).strip()

        heading_stack[level - 1] = title
        for j in range(level, 3):            # clear lower-level headings
            heading_stack[j] = ""

        heading_path = " > ".join(h for h in heading_stack if h)

        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        if body:
            sections.append((heading_path, body))

    return sections


def _split_by_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_by_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _merge_into_chunks(
    paragraphs: List[str],
    target: int,
    max_tokens: int,
    overlap: int,
    placeholders: Dict[str, str],
) -> List[str]:
    """Merge paragraph-level units into token-bounded chunks.

    Rules:
    - Paragraphs containing fence placeholders are atomic (never sentence-split).
    - Non-atomic paragraphs exceeding max_tokens are split on sentence boundaries.
    - When a bucket overflows, it is flushed. If overlap > 0, the trailing
      paragraphs/sentences that fit within `overlap` tokens seed the next bucket.
    """
    result: List[str] = []
    bucket: List[str] = []
    bucket_tokens = 0

    def flush() -> None:
        nonlocal bucket_tokens
        if bucket:
            result.append("\n\n".join(bucket))
            bucket.clear()
            bucket_tokens = 0

    def flush_with_overlap() -> None:
        nonlocal bucket_tokens
        if not bucket:
            return
        result.append("\n\n".join(bucket))
        if overlap > 0:
            tail: List[str] = []
            tail_tokens = 0
            for item in reversed(bucket):
                t = count_tokens(item)
                if tail_tokens + t <= overlap:
                    tail.insert(0, item)
                    tail_tokens += t
                else:
                    break
            bucket.clear()
            bucket.extend(tail)
            bucket_tokens = tail_tokens
        else:
            bucket.clear()
            bucket_tokens = 0

    for para in paragraphs:
        is_atomic = any(key in para for key in placeholders)
        para_restored = _restore_fences(para, placeholders)
        para_tokens = count_tokens(para_restored)

        if is_atomic:
            # Flush current bucket; fence becomes its own chunk regardless of size
            flush()
            result.append(para_restored)
            continue

        if para_tokens > max_tokens:
            # Sentence-level fallback for oversized non-fence paragraphs
            flush()
            for sentence in _split_by_sentences(para_restored):
                s_tokens = count_tokens(sentence)
                if bucket_tokens + s_tokens > max_tokens:
                    flush_with_overlap()
                bucket.append(sentence)
                bucket_tokens += s_tokens
        else:
            if bucket_tokens + para_tokens > max_tokens:
                flush_with_overlap()
            bucket.append(para_restored)
            bucket_tokens += para_tokens

    if bucket:
        result.append("\n\n".join(bucket))

    return result


def chunk_document(content: str, source: str) -> List[Chunk]:
    """Hybrid chunking: headings → paragraphs → sentences; code fences are atomic.

    Args:
        content: Full markdown document text.
        source: Filename or URL used as chunk metadata source field.

    Returns:
        Ordered list of Chunk objects with sequential chunk_index.
    """
    if not content.strip():
        return []

    content_type = detect_content_type(content)

    if content_type == "article":
        target, max_tokens, overlap = ARTICLE_TARGET, ARTICLE_MAX, ARTICLE_OVERLAP
    else:
        target, max_tokens, overlap = TRANSCRIPTION_TARGET, TRANSCRIPTION_MAX, TRANSCRIPTION_OVERLAP

    # Protect code fences before any splitting
    modified, placeholders = _extract_code_fences(content)
    sections = _split_by_headings(modified)

    chunks: List[Chunk] = []
    chunk_index = 0

    for heading_path, section_text in sections:
        # Restore fences for token counting (section may contain fence placeholders)
        section_restored = _restore_fences(section_text, placeholders)

        if count_tokens(section_restored) <= target:
            # Section fits in one chunk
            chunks.append(
                Chunk(
                    content=section_restored,
                    chunk_index=chunk_index,
                    metadata={
                        "source": source,
                        "heading_path": heading_path,
                        "content_type": content_type,
                        "char_count": len(section_restored),
                    },
                )
            )
            chunk_index += 1
        else:
            # Split section further; keep placeholders intact during paragraph split
            paragraphs = _split_by_paragraphs(section_text)
            merged = _merge_into_chunks(paragraphs, target, max_tokens, overlap, placeholders)
            for chunk_text in merged:
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        chunk_index=chunk_index,
                        metadata={
                            "source": source,
                            "heading_path": heading_path,
                            "content_type": content_type,
                            "char_count": len(chunk_text),
                        },
                    )
                )
                chunk_index += 1

    return chunks
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_services/test_chunking.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/services/chunking.py \
        apps/backend/tests/unit/test_services/test_chunking.py
git commit -m "feat(ingestion): add hybrid chunking service with code fence protection"
```

---

### Task 3: Tavily URL Crawl Service

**Files:**
- Create: `apps/backend/src/second_brain/services/tavily.py`
- Create: `apps/backend/tests/unit/test_services/test_tavily.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_services/test_tavily.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_crawl_url_returns_raw_content():
    """crawl_url must return the raw_content string from Tavily extract."""
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(
        return_value={
            "results": [{"raw_content": "# Scraped Page\n\nBody text here."}]
        }
    )

    with patch("second_brain.services.tavily.AsyncTavilyClient", return_value=mock_client):
        from second_brain.services.tavily import crawl_url
        result = await crawl_url("https://example.com/article")

    assert result == "# Scraped Page\n\nBody text here."


@pytest.mark.asyncio
async def test_crawl_url_raises_when_no_results():
    """crawl_url must raise ValueError when Tavily returns empty results."""
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value={"results": []})

    with patch("second_brain.services.tavily.AsyncTavilyClient", return_value=mock_client):
        from second_brain.services.tavily import crawl_url
        with pytest.raises(ValueError, match="no content"):
            await crawl_url("https://example.com/empty")


@pytest.mark.asyncio
async def test_crawl_and_save_writes_markdown_file(tmp_path):
    """crawl_and_save must save crawled content as a .md file and return its path."""
    pending_dir = tmp_path / "pending-digest-docs"
    pending_dir.mkdir()

    with patch("second_brain.services.tavily.AsyncTavilyClient") as mock_cls, \
         patch("second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir):
        mock_client = AsyncMock()
        mock_client.extract = AsyncMock(
            return_value={"results": [{"raw_content": "# Hello\n\nWorld."}]}
        )
        mock_cls.return_value = mock_client

        from second_brain.services.tavily import crawl_and_save
        saved_path = await crawl_and_save("https://example.com/page")

    assert saved_path.exists()
    assert saved_path.suffix == ".md"
    assert saved_path.read_text() == "# Hello\n\nWorld."


@pytest.mark.asyncio
async def test_crawl_and_save_slugifies_url_to_filename(tmp_path):
    """crawl_and_save filename must be derived from the URL, not random."""
    pending_dir = tmp_path / "pending-digest-docs"
    pending_dir.mkdir()

    with patch("second_brain.services.tavily.AsyncTavilyClient") as mock_cls, \
         patch("second_brain.services.tavily.PENDING_DOCS_DIR", pending_dir):
        mock_client = AsyncMock()
        mock_client.extract = AsyncMock(
            return_value={"results": [{"raw_content": "content"}]}
        )
        mock_cls.return_value = mock_client

        from second_brain.services.tavily import crawl_and_save
        saved_path = await crawl_and_save("https://example.com/my-article")

    # Filename must contain recognisable parts of the URL
    assert "example" in saved_path.name
    assert saved_path.name.endswith(".md")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_services/test_tavily.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.services.tavily'`

- [ ] **Step 3: Implement the Tavily service**

```python
# apps/backend/src/second_brain/services/tavily.py
import os
import re
from pathlib import Path

from tavily import AsyncTavilyClient

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
PENDING_DOCS_DIR = Path("temp/pending-digest-docs")


def _url_to_slug(url: str) -> str:
    """Convert a URL into a safe filename stem (max 80 chars)."""
    slug = re.sub(r"https?://", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug)
    return slug.strip("-")[:80]


async def crawl_url(url: str) -> str:
    """Extract markdown content from a URL via Tavily.

    Returns:
        Raw content string from the first Tavily result.

    Raises:
        ValueError: If Tavily returns no results for the URL.
    """
    client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
    response = await client.extract(urls=[url])
    results = response.get("results", [])
    if not results:
        raise ValueError(f"Tavily returned no content for URL: {url}")
    return results[0].get("raw_content", "")


async def crawl_and_save(url: str) -> Path:
    """Crawl a URL and save the content as a markdown file.

    Saves to PENDING_DOCS_DIR/<url-slug>.md and returns the Path.
    """
    content = await crawl_url(url)
    slug = _url_to_slug(url)
    filepath = PENDING_DOCS_DIR / f"{slug}.md"
    PENDING_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    return filepath
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_services/test_tavily.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/services/tavily.py \
        apps/backend/tests/unit/test_services/test_tavily.py
git commit -m "feat(ingestion): add Tavily URL crawl service"
```

---

### Task 4: IngestionState TypedDicts

**Files:**
- Create: `apps/backend/src/second_brain/graphs/state.py`
- Create: `apps/backend/tests/unit/test_graphs/test_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_graphs/test_state.py
import pytest
from second_brain.graphs.state import FailedFile, IngestionState


def test_failed_file_typeddict_construction():
    """FailedFile can be constructed with all required keys."""
    item: FailedFile = {
        "filename": "broken.md",
        "error": "Connection refused",
        "retry_count": 2,
    }
    assert item["filename"] == "broken.md"
    assert item["error"] == "Connection refused"
    assert item["retry_count"] == 2


def test_ingestion_state_typeddict_construction():
    """IngestionState can be constructed with all required keys."""
    state: IngestionState = {
        "files": ["a.md", "b.md"],
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }
    assert state["files"] == ["a.md", "b.md"]
    assert state["in_progress"] == []
    assert state["processed"] == []
    assert state["retry_queue"] == []
    assert state["failed"] == []


def test_ingestion_state_with_failed_file_in_retry_queue():
    """IngestionState retry_queue accepts FailedFile dicts."""
    failed: FailedFile = {"filename": "c.md", "error": "Timeout", "retry_count": 1}
    state: IngestionState = {
        "files": [],
        "in_progress": ["c.md"],
        "processed": ["a.md"],
        "retry_queue": [failed],
        "failed": [],
    }
    assert state["retry_queue"][0]["retry_count"] == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_graphs/test_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.graphs.state'`

- [ ] **Step 3: Implement the state module**

```python
# apps/backend/src/second_brain/graphs/state.py
from typing import TypedDict


class FailedFile(TypedDict):
    filename: str
    error: str
    retry_count: int


class IngestionState(TypedDict):
    files: list[str]                # original input queue (first-attempt files)
    in_progress: list[str]          # crash-safe in-flight tracking (0 or 1 item)
    processed: list[str]            # successfully ingested filenames
    retry_queue: list[FailedFile]   # retry_count < 3 (terminal threshold)
    failed: list[FailedFile]        # terminal failures: retry_count >= 3
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_graphs/test_state.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/graphs/__init__.py \
        apps/backend/src/second_brain/graphs/state.py \
        apps/backend/tests/unit/test_graphs/__init__.py \
        apps/backend/tests/unit/test_graphs/test_state.py
git commit -m "feat(ingestion): add IngestionState and FailedFile TypedDicts"
```

---

### Task 5: Ingestion Agent Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/ingestion_agent.py`
- Create: `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py`

**Context:** This module contains `ingestion_agent_node`, the LangGraph node that processes one file per call. It:
1. Reads the file from `in_progress[0]`
2. Computes MD5 — skips if already in `ingested_documents`
3. Generates a 50–100 token contextual header per chunk via `claude-haiku-4-5`
4. Embeds `header + chunk` via Ollama
5. Upserts `DocumentChunk` and `IngestedDocument` records
6. Moves the file to `processed/` on success or increments retry on failure

`IngestedDocument` and `DocumentChunk` SQLModel models are already defined in `apps/backend/src/second_brain/db/models.py` (Ticket 1). The `engine` is available in `apps/backend/src/second_brain/db/session.py`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_ingestion_agent.py
import pytest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from second_brain.graphs.state import FailedFile, IngestionState


def _make_state(**overrides) -> IngestionState:
    base: IngestionState = {
        "files": [],
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_successful_ingest_moves_file_to_processed(tmp_path):
    """On successful ingest, filename moves from in_progress to processed."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    (pending / "note.md").write_text("# Note\n\nContent here.\n")

    fake_embedding = [0.0] * 1024

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending), \
         patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", processed), \
         patch("second_brain.nodes.ingestion_agent.embed_text", AsyncMock(return_value=fake_embedding)), \
         patch("second_brain.nodes.ingestion_agent._generate_contextual_header",
               AsyncMock(return_value="This chunk is from note.md, section Note, covering content.")), \
         patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None  # no duplicate
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node
        state = _make_state(in_progress=["note.md"])
        result = await ingestion_agent_node(state)

    assert "note.md" in result["processed"]
    assert result["in_progress"] == []
    assert (processed / "note.md").exists()


@pytest.mark.asyncio
async def test_duplicate_file_is_skipped_and_moved_to_processed(tmp_path):
    """If content_hash matches an existing record, file is skipped (not re-embedded)."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    (pending / "dupe.md").write_text("# Dupe\n\nSame content.\n")

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending), \
         patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", processed), \
         patch("second_brain.nodes.ingestion_agent.embed_text", AsyncMock()) as mock_embed, \
         patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # Simulate duplicate: exec().first() returns an existing record
        mock_session.exec.return_value.first.return_value = MagicMock()
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node
        state = _make_state(in_progress=["dupe.md"])
        result = await ingestion_agent_node(state)

    mock_embed.assert_not_called()
    assert "dupe.md" in result["processed"]
    assert (processed / "dupe.md").exists()


@pytest.mark.asyncio
async def test_first_failure_goes_to_retry_queue(tmp_path):
    """First failure increments retry_count to 1 and adds to retry_queue."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    (pending / "bad.md").write_text("# Bad\n\nContent.\n")

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending), \
         patch("second_brain.nodes.ingestion_agent.embed_text",
               AsyncMock(side_effect=RuntimeError("Ollama down"))), \
         patch("second_brain.nodes.ingestion_agent._generate_contextual_header",
               AsyncMock(return_value="header")), \
         patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node
        state = _make_state(in_progress=["bad.md"])
        result = await ingestion_agent_node(state)

    assert result["in_progress"] == []
    retry_entries = [f for f in result["retry_queue"] if f["filename"] == "bad.md"]
    assert len(retry_entries) == 1
    assert retry_entries[0]["retry_count"] == 1
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_third_failure_moves_to_failed_and_moves_file(tmp_path):
    """After retry_count reaches MAX_RETRIES (3), file moves to failed state and failed/ dir."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    (pending / "broken.md").write_text("# Broken\n\nContent.\n")

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", pending), \
         patch("second_brain.nodes.ingestion_agent.FAILED_DIR", failed_dir), \
         patch("second_brain.nodes.ingestion_agent.embed_text",
               AsyncMock(side_effect=RuntimeError("permanent error"))), \
         patch("second_brain.nodes.ingestion_agent._generate_contextual_header",
               AsyncMock(return_value="header")), \
         patch("second_brain.nodes.ingestion_agent.Session") as mock_session_cls:

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_session_cls.return_value = mock_session

        from second_brain.nodes.ingestion_agent import ingestion_agent_node
        # Simulate already at retry_count=2 (next failure hits limit of 3)
        state = _make_state(
            in_progress=["broken.md"],
            retry_queue=[{"filename": "broken.md", "error": "err", "retry_count": 2}],
        )
        result = await ingestion_agent_node(state)

    assert result["in_progress"] == []
    assert result["retry_queue"] == []
    failed_entries = [f for f in result["failed"] if f["filename"] == "broken.md"]
    assert len(failed_entries) == 1
    assert failed_entries[0]["retry_count"] == 3
    assert (failed_dir / "broken.md").exists()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_nodes/test_ingestion_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.nodes.ingestion_agent'`

- [ ] **Step 3: Implement the ingestion agent node**

```python
# apps/backend/src/second_brain/nodes/ingestion_agent.py
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from sqlmodel import Session, select

from second_brain.db.models import DocumentChunk, IngestedDocument
from second_brain.db.session import engine
from second_brain.graphs.state import FailedFile, IngestionState
from second_brain.services.chunking import chunk_document
from second_brain.services.embeddings import embed_text

PENDING_DOCS_DIR = Path("temp/pending-digest-docs")
PROCESSED_DIR = Path("temp/processed")
FAILED_DIR = Path("temp/failed")

MAX_RETRIES = 3  # terminal when retry_count >= MAX_RETRIES

_anthropic = anthropic.AsyncAnthropic()


def _compute_md5(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


async def _generate_contextual_header(
    filename: str, heading_path: str, chunk_content: str
) -> str:
    """Generate a 50–100 token context header for a chunk using claude-haiku-4-5."""
    prompt = (
        "Write a single-sentence context header (50–100 tokens) for this document chunk.\n"
        f"Document: {filename}\n"
        f"Section: {heading_path or 'N/A'}\n"
        f"Chunk preview: {chunk_content[:300]}\n\n"
        "Format exactly: "
        "'This chunk is from [filename], section [section], covering [brief topic].'\n"
        "Output only the header sentence, nothing else."
    )
    response = await _anthropic.messages.create(
        model="claude-haiku-4-5",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def _do_ingest(
    filename: str, session: Session, source_url: Optional[str] = None
) -> None:
    """Read, chunk, embed, and store one markdown file.

    On duplicate content hash: moves file to processed/ without re-embedding.
    Raises any exception to the caller for retry handling.
    """
    filepath = PENDING_DOCS_DIR / filename
    content = filepath.read_text(encoding="utf-8")
    content_hash = _compute_md5(content)

    # Deduplication: skip if content already ingested
    existing = session.exec(
        select(IngestedDocument).where(IngestedDocument.content_hash == content_hash)
    ).first()
    if existing:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        filepath.rename(PROCESSED_DIR / filename)
        return

    doc_id = uuid.uuid4()
    chunks = chunk_document(content, source=filename)

    for chunk in chunks:
        header = await _generate_contextual_header(
            filename=filename,
            heading_path=chunk.metadata["heading_path"],
            chunk_content=chunk.content,
        )
        embedded_text = f"{header}\n\n{chunk.content}"
        embedding = await embed_text(embedded_text)

        session.add(
            DocumentChunk(
                id=uuid.uuid4(),
                doc_id=doc_id,
                content=embedded_text,
                embedding=embedding,
                chunk_index=chunk.chunk_index,
                metadata=chunk.metadata,
                created_at=datetime.now(timezone.utc),
            )
        )

    session.add(
        IngestedDocument(
            id=doc_id,
            filename=filename,
            source_url=source_url,
            content_hash=content_hash,
            status="processed",
            ingested_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    filepath.rename(PROCESSED_DIR / filename)


async def ingestion_agent_node(state: IngestionState) -> dict:
    """LangGraph node: process in_progress[0], update state on success or failure.

    On success  → moves filename to processed, clears in_progress.
    On failure  → increments retry_count; routes to retry_queue (<3) or failed (>=3).
    Terminal    → moves file to FAILED_DIR and adds to failed list.
    """
    filename = state["in_progress"][0]

    # Find existing retry metadata (if this is a retry attempt)
    retry_item = next(
        (f for f in state["retry_queue"] if f["filename"] == filename), None
    )
    current_count: int = retry_item["retry_count"] if retry_item else 0
    # Remove this file from retry_queue (will be re-added if it fails again)
    new_retry_queue = [f for f in state["retry_queue"] if f["filename"] != filename]

    try:
        with Session(engine) as session:
            await _do_ingest(filename, session)

        return {
            "processed": state["processed"] + [filename],
            "in_progress": [],
            "retry_queue": new_retry_queue,
        }

    except Exception as exc:
        error_msg = str(exc)
        next_count = current_count + 1

        if next_count < MAX_RETRIES:
            failed_entry: FailedFile = {
                "filename": filename,
                "error": error_msg,
                "retry_count": next_count,
            }
            return {
                "in_progress": [],
                "retry_queue": new_retry_queue + [failed_entry],
            }
        else:
            # Terminal failure — move file to failed/ directory
            FAILED_DIR.mkdir(parents=True, exist_ok=True)
            src = PENDING_DOCS_DIR / filename
            if src.exists():
                src.rename(FAILED_DIR / filename)

            terminal_entry: FailedFile = {
                "filename": filename,
                "error": error_msg,
                "retry_count": next_count,
            }
            return {
                "in_progress": [],
                "retry_queue": new_retry_queue,
                "failed": state["failed"] + [terminal_entry],
            }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_nodes/test_ingestion_agent.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/__init__.py \
        apps/backend/src/second_brain/nodes/ingestion_agent.py \
        apps/backend/tests/unit/test_nodes/__init__.py \
        apps/backend/tests/unit/test_nodes/test_ingestion_agent.py
git commit -m "feat(ingestion): add ingestion agent LangGraph node with retry logic"
```

---

### Task 6: Ingestion Graph

**Files:**
- Create: `apps/backend/src/second_brain/graphs/ingestion_graph.py`
- Create: `apps/backend/tests/unit/test_graphs/test_ingestion_graph.py`

**Context:** The graph wires together two nodes:
- `pick_file` — moves the next pending or retry file into `in_progress`
- `ingest` — calls `ingestion_agent_node`

After `ingest`, a conditional edge checks whether there are remaining `files` or `retry_queue` items. If yes: loops back to `pick_file`. If no: terminates.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_graphs/test_ingestion_graph.py
import pytest
from unittest.mock import AsyncMock, patch

from second_brain.graphs.state import IngestionState


def _make_state(**overrides) -> IngestionState:
    base: IngestionState = {
        "files": [],
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_graph_processes_single_file():
    """Graph with one file in files[] should result in that file in processed."""
    async def fake_ingest_node(state):
        filename = state["in_progress"][0]
        return {
            "processed": state["processed"] + [filename],
            "in_progress": [],
            "retry_queue": state["retry_queue"],
        }

    with patch("second_brain.graphs.ingestion_graph.ingestion_agent_node", fake_ingest_node):
        from second_brain.graphs.ingestion_graph import build_ingestion_graph
        graph = build_ingestion_graph()
        initial = _make_state(files=["a.md"])
        result = await graph.ainvoke(initial)

    assert "a.md" in result["processed"]
    assert result["failed"] == []
    assert result["in_progress"] == []


@pytest.mark.asyncio
async def test_graph_processes_multiple_files_sequentially():
    """Graph with two files must process both."""
    async def fake_ingest_node(state):
        filename = state["in_progress"][0]
        return {
            "processed": state["processed"] + [filename],
            "in_progress": [],
            "retry_queue": [],
        }

    with patch("second_brain.graphs.ingestion_graph.ingestion_agent_node", fake_ingest_node):
        from second_brain.graphs.ingestion_graph import build_ingestion_graph
        graph = build_ingestion_graph()
        initial = _make_state(files=["a.md", "b.md"])
        result = await graph.ainvoke(initial)

    assert set(result["processed"]) == {"a.md", "b.md"}
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_graph_retries_failed_file():
    """A file that fails on first attempt (retry_count=1) must be retried."""
    call_count = {"n": 0}

    async def fake_ingest_node(state):
        filename = state["in_progress"][0]
        retry_item = next(
            (f for f in state["retry_queue"] if f["filename"] == filename), None
        )
        new_retry_queue = [f for f in state["retry_queue"] if f["filename"] != filename]
        call_count["n"] += 1

        if call_count["n"] == 1:
            # First attempt: fail and add to retry_queue
            return {
                "in_progress": [],
                "retry_queue": new_retry_queue + [
                    {"filename": filename, "error": "transient", "retry_count": 1}
                ],
            }
        else:
            # Second attempt (retry): succeed
            return {
                "processed": state["processed"] + [filename],
                "in_progress": [],
                "retry_queue": new_retry_queue,
            }

    with patch("second_brain.graphs.ingestion_graph.ingestion_agent_node", fake_ingest_node):
        from second_brain.graphs.ingestion_graph import build_ingestion_graph
        graph = build_ingestion_graph()
        initial = _make_state(files=["flaky.md"])
        result = await graph.ainvoke(initial)

    assert "flaky.md" in result["processed"]
    assert result["failed"] == []
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_graph_terminates_when_all_files_done():
    """Graph must terminate (not loop forever) once all files are processed."""
    async def fake_ingest_node(state):
        filename = state["in_progress"][0]
        return {
            "processed": state["processed"] + [filename],
            "in_progress": [],
            "retry_queue": [],
        }

    with patch("second_brain.graphs.ingestion_graph.ingestion_agent_node", fake_ingest_node):
        from second_brain.graphs.ingestion_graph import build_ingestion_graph
        graph = build_ingestion_graph()
        result = await graph.ainvoke(_make_state(files=["x.md"]))

    assert result["files"] == []
    assert result["retry_queue"] == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_graphs/test_ingestion_graph.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.graphs.ingestion_graph'`

- [ ] **Step 3: Implement the ingestion graph**

```python
# apps/backend/src/second_brain/graphs/ingestion_graph.py
from langgraph.graph import END, StateGraph

from second_brain.graphs.state import IngestionState
from second_brain.nodes.ingestion_agent import ingestion_agent_node


def pick_file_node(state: IngestionState) -> dict:
    """Move the next pending or retry file into in_progress.

    Priority: files[] (first-timers) before retry_queue.
    Does NOT remove the item from retry_queue — ingestion_agent_node does that
    after the attempt to preserve retry metadata for retry_count tracking.
    """
    if state["files"]:
        return {
            "files": state["files"][1:],
            "in_progress": [state["files"][0]],
        }
    if state["retry_queue"]:
        return {
            "in_progress": [state["retry_queue"][0]["filename"]],
        }
    return {"in_progress": []}


def _route_after_ingest(state: IngestionState) -> str:
    """Continue looping if there are more files or retries; else terminate."""
    if state["files"] or state["retry_queue"]:
        return "pick_file"
    return END


def build_ingestion_graph() -> StateGraph:
    builder = StateGraph(IngestionState)

    builder.add_node("pick_file", pick_file_node)
    builder.add_node("ingest", ingestion_agent_node)

    builder.set_entry_point("pick_file")
    builder.add_edge("pick_file", "ingest")
    builder.add_conditional_edges(
        "ingest",
        _route_after_ingest,
        {"pick_file": "pick_file", END: END},
    )

    return builder.compile()


# Module-level singleton used by the API router
ingestion_graph = build_ingestion_graph()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_graphs/test_ingestion_graph.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/graphs/ingestion_graph.py \
        apps/backend/tests/unit/test_graphs/test_ingestion_graph.py
git commit -m "feat(ingestion): add LangGraph ingestion graph with retry loop"
```

---

### Task 7: API Schemas

**Files:**
- Create: `apps/backend/src/second_brain/api/schemas.py`
- Create: `apps/backend/tests/unit/test_api/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_api/test_schemas.py
import pytest
from pydantic import ValidationError

from second_brain.api.schemas import IngestFileResponse, IngestUrlRequest


def test_ingest_file_response_valid():
    resp = IngestFileResponse(numberOfFilePassed=5, failedFiles=["bad.md"])
    assert resp.numberOfFilePassed == 5
    assert resp.failedFiles == ["bad.md"]


def test_ingest_file_response_serializes_to_camel_case_keys():
    resp = IngestFileResponse(numberOfFilePassed=2, failedFiles=[])
    data = resp.model_dump()
    assert "numberOfFilePassed" in data
    assert "failedFiles" in data


def test_ingest_file_response_defaults_empty_failed_files():
    resp = IngestFileResponse(numberOfFilePassed=0, failedFiles=[])
    assert resp.failedFiles == []


def test_ingest_url_request_valid():
    req = IngestUrlRequest(urls=["https://example.com", "https://other.com"])
    assert len(req.urls) == 2
    assert req.urls[0] == "https://example.com"


def test_ingest_url_request_rejects_missing_urls():
    with pytest.raises(ValidationError):
        IngestUrlRequest()  # urls is required
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_api/test_schemas.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.api.schemas'`

- [ ] **Step 3: Implement the schemas**

```python
# apps/backend/src/second_brain/api/schemas.py
from pydantic import BaseModel


class IngestFileResponse(BaseModel):
    numberOfFilePassed: int
    failedFiles: list[str]


class IngestUrlRequest(BaseModel):
    urls: list[str]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_api/test_schemas.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/api/__init__.py \
        apps/backend/src/second_brain/api/schemas.py \
        apps/backend/tests/unit/test_api/__init__.py \
        apps/backend/tests/unit/test_api/test_schemas.py
git commit -m "feat(ingestion): add IngestFileResponse and IngestUrlRequest schemas"
```

---

### Task 8: Ingest Router

**Files:**
- Create: `apps/backend/src/second_brain/api/routers/ingest.py`
- Create: `apps/backend/tests/unit/test_api/test_routers/test_ingest.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_api/test_routers/test_ingest.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport
from second_brain.main import app


@pytest.mark.asyncio
async def test_ingest_file_empty_directory_returns_zero_passed(tmp_path):
    """POST /ingest/file with no .md files returns numberOfFilePassed=0."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()

    with patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", pending):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    assert response.status_code == 200
    data = response.json()
    assert data["numberOfFilePassed"] == 0
    assert data["failedFiles"] == []


@pytest.mark.asyncio
async def test_ingest_file_invokes_graph_with_pending_files(tmp_path):
    """POST /ingest/file discovers .md files and invokes ingestion_graph."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    (pending / "doc1.md").write_text("content")
    (pending / "doc2.md").write_text("content")

    mock_final_state = {
        "processed": ["doc1.md", "doc2.md"],
        "failed": [],
        "files": [],
        "in_progress": [],
        "retry_queue": [],
    }

    with patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", pending), \
         patch("second_brain.api.routers.ingest.ingestion_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    assert response.status_code == 200
    data = response.json()
    assert data["numberOfFilePassed"] == 2
    assert data["failedFiles"] == []


@pytest.mark.asyncio
async def test_ingest_file_reports_failed_files(tmp_path):
    """POST /ingest/file returns failed filenames from final graph state."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    (pending / "bad.md").write_text("content")

    mock_final_state = {
        "processed": [],
        "failed": [{"filename": "bad.md", "error": "err", "retry_count": 3}],
        "files": [],
        "in_progress": [],
        "retry_queue": [],
    }

    with patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", pending), \
         patch("second_brain.api.routers.ingest.ingestion_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    data = response.json()
    assert data["numberOfFilePassed"] == 0
    assert "bad.md" in data["failedFiles"]


@pytest.mark.asyncio
async def test_ingest_url_crawls_and_invokes_graph():
    """POST /ingest/url crawls URLs via Tavily then invokes ingestion_graph."""
    mock_final_state = {
        "processed": ["example-com-page.md"],
        "failed": [],
        "files": [],
        "in_progress": [],
        "retry_queue": [],
    }

    fake_saved_path = Path("temp/pending-digest-docs/example-com-page.md")

    with patch("second_brain.api.routers.ingest.crawl_and_save",
               AsyncMock(return_value=fake_saved_path)) as mock_crawl, \
         patch("second_brain.api.routers.ingest.ingestion_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ingest/url",
                json={"urls": ["https://example.com/page"]},
            )

    assert response.status_code == 200
    mock_crawl.assert_called_once_with("https://example.com/page")
    data = response.json()
    assert data["numberOfFilePassed"] == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_api/test_routers/test_ingest.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.api.routers.ingest'`

- [ ] **Step 3: Implement the ingest router**

```python
# apps/backend/src/second_brain/api/routers/ingest.py
from pathlib import Path

from fastapi import APIRouter

from second_brain.api.schemas import IngestFileResponse, IngestUrlRequest
from second_brain.graphs.ingestion_graph import ingestion_graph
from second_brain.graphs.state import IngestionState
from second_brain.services.tavily import crawl_and_save

router = APIRouter(prefix="/ingest", tags=["ingest"])

PENDING_DOCS_DIR = Path("temp/pending-digest-docs")


@router.post("/file", response_model=IngestFileResponse)
async def ingest_file() -> IngestFileResponse:
    """Ingest all .md files currently in temp/pending-digest-docs/.

    Returns the count of successfully ingested files and any terminal failures.
    Files are moved to temp/processed/ on success or temp/failed/ after 3 attempts.
    """
    PENDING_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    files = [f.name for f in PENDING_DOCS_DIR.glob("*.md")]

    if not files:
        return IngestFileResponse(numberOfFilePassed=0, failedFiles=[])

    initial_state: IngestionState = {
        "files": files,
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }

    final_state = await ingestion_graph.ainvoke(initial_state)

    return IngestFileResponse(
        numberOfFilePassed=len(final_state["processed"]),
        failedFiles=[f["filename"] for f in final_state["failed"]],
    )


@router.post("/url", response_model=IngestFileResponse)
async def ingest_url(request: IngestUrlRequest) -> IngestFileResponse:
    """Crawl each URL via Tavily, save as markdown, then ingest via the same pipeline.

    URLs are crawled sequentially. Saved files go through the normal ingestion graph
    with identical retry and deduplication semantics as /ingest/file.
    """
    saved_files: list[str] = []
    for url in request.urls:
        filepath = await crawl_and_save(url)
        saved_files.append(filepath.name)

    if not saved_files:
        return IngestFileResponse(numberOfFilePassed=0, failedFiles=[])

    initial_state: IngestionState = {
        "files": saved_files,
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }

    final_state = await ingestion_graph.ainvoke(initial_state)

    return IngestFileResponse(
        numberOfFilePassed=len(final_state["processed"]),
        failedFiles=[f["filename"] for f in final_state["failed"]],
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_api/test_routers/test_ingest.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/api/routers/__init__.py \
        apps/backend/src/second_brain/api/routers/ingest.py \
        apps/backend/tests/unit/test_api/test_routers/__init__.py \
        apps/backend/tests/unit/test_api/test_routers/test_ingest.py
git commit -m "feat(ingestion): add POST /ingest/file and POST /ingest/url endpoints"
```

---

### Task 9: Register Router in main.py

**Files:**
- Modify: `apps/backend/src/second_brain/main.py`

No TDD for this step — it is pure FastAPI wiring. Read the existing `main.py` first.

- [ ] **Step 1: Read the current main.py**

```bash
cat apps/backend/src/second_brain/main.py
```

- [ ] **Step 2: Add the ingest router registration**

Add these two lines to `main.py`. The `from ...` import goes with the other router imports; `app.include_router(...)` goes with the other `include_router` calls.

```python
from second_brain.api.routers.ingest import router as ingest_router

app.include_router(ingest_router)
```

Example of what the relevant section of `main.py` should look like after the edit:

```python
from fastapi import FastAPI
from second_brain.api.routers.ingest import router as ingest_router
# ... other existing imports ...

app = FastAPI(title="Second Brain")

app.include_router(ingest_router)
# ... other existing include_router calls ...
```

- [ ] **Step 3: Verify the routes are registered**

```bash
cd apps/backend && python -c "
from second_brain.main import app
routes = [r.path for r in app.routes]
assert '/ingest/file' in routes, f'Missing /ingest/file. Routes: {routes}'
assert '/ingest/url' in routes, f'Missing /ingest/url. Routes: {routes}'
print('OK — both routes registered:', [r for r in routes if r.startswith('/ingest')])
"
```

Expected output: `OK — both routes registered: ['/ingest/file', '/ingest/url']`

- [ ] **Step 4: Run full unit test suite to confirm nothing broken**

```bash
pytest tests/unit/ -v
```

Expected: all unit tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/main.py
git commit -m "feat(ingestion): register ingest router in FastAPI app"
```

---

### Task 10: Integration Test — Full Ingestion Flow

**Files:**
- Create: `apps/backend/tests/integration/test_ingestion_graph.py`

**Context:** This test exercises the complete pipeline with real LangGraph graph logic and real chunking. External dependencies (Ollama, Anthropic) are mocked. The test requires the PostgreSQL database to be running (`docker compose up -d app_postgres`). The `engine` from `second_brain.db.session` is used directly.

**Before running:** ensure the Docker stack is up and migrations have run:
```bash
docker compose up -d app_postgres
cd apps/backend && alembic upgrade head
```

- [ ] **Step 1: Write the integration test**

```python
# apps/backend/tests/integration/test_ingestion_graph.py
"""Integration test for the full document ingestion pipeline.

Requirements:
    - PostgreSQL running (docker compose up -d app_postgres)
    - Alembic migrations applied (alembic upgrade head)
    - Ollama and Anthropic are mocked — no live API keys required.
"""
import pytest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from second_brain.db.models import DocumentChunk, IngestedDocument
from second_brain.db.session import engine
from second_brain.graphs.state import IngestionState


FAKE_EMBEDDING = [0.01] * 1024
FAKE_HEADER = "This chunk is from test-note.md, section Test Note, covering integration testing."


@pytest.fixture()
def tmp_dirs(tmp_path):
    """Create temp/pending-digest-docs, temp/processed, temp/failed directories."""
    pending = tmp_path / "pending-digest-docs"
    pending.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    failed = tmp_path / "failed"
    failed.mkdir()
    return {"pending": pending, "processed": processed, "failed": failed}


@pytest.fixture(autouse=True)
def clean_db():
    """Remove test records inserted during the test to avoid cross-test contamination."""
    yield
    with Session(engine) as session:
        # Clean up any test documents (those with filenames starting with "test-")
        from sqlmodel import delete
        session.exec(
            delete(DocumentChunk).where(
                DocumentChunk.doc_id.in_(
                    select(IngestedDocument.id).where(
                        IngestedDocument.filename.like("test-%")
                    )
                )
            )
        )
        session.exec(
            delete(IngestedDocument).where(IngestedDocument.filename.like("test-%"))
        )
        session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_ingest_file_success(tmp_dirs):
    """A .md file in pending-digest-docs/ is fully processed and moved to processed/."""
    test_file = tmp_dirs["pending"] / "test-note.md"
    test_file.write_text(
        "# Test Note\n\nThis document covers integration testing.\n\n"
        "## Details\n\nMore detail content here for verification.\n"
    )

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", tmp_dirs["pending"]), \
         patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", tmp_dirs["processed"]), \
         patch("second_brain.nodes.ingestion_agent.FAILED_DIR", tmp_dirs["failed"]), \
         patch("second_brain.nodes.ingestion_agent.embed_text",
               AsyncMock(return_value=FAKE_EMBEDDING)), \
         patch("second_brain.nodes.ingestion_agent._generate_contextual_header",
               AsyncMock(return_value=FAKE_HEADER)):

        from second_brain.graphs.ingestion_graph import build_ingestion_graph
        graph = build_ingestion_graph()

        initial: IngestionState = {
            "files": ["test-note.md"],
            "in_progress": [],
            "processed": [],
            "retry_queue": [],
            "failed": [],
        }
        final = await graph.ainvoke(initial)

    # State assertions
    assert "test-note.md" in final["processed"], f"processed={final['processed']}"
    assert final["failed"] == []
    assert final["in_progress"] == []

    # File system assertions
    assert (tmp_dirs["processed"] / "test-note.md").exists(), "File must move to processed/"
    assert not (tmp_dirs["pending"] / "test-note.md").exists(), "File must not remain in pending/"

    # Database assertions
    with Session(engine) as session:
        doc = session.exec(
            select(IngestedDocument).where(IngestedDocument.filename == "test-note.md")
        ).first()
        assert doc is not None, "IngestedDocument record must be created"
        assert doc.status == "processed"
        assert doc.content_hash is not None

        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.doc_id == doc.id)
        ).all()
        assert len(chunks) >= 1, "At least one DocumentChunk must be created"
        for chunk in chunks:
            assert len(chunk.embedding) == 1024, "Embedding must be 1024-dimensional"
            assert chunk.content, "Chunk content must not be empty"
            assert FAKE_HEADER in chunk.content, "Contextual header must be prepended"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_duplicate_file_is_skipped_on_reingest(tmp_dirs):
    """Re-ingesting the same file content (matching MD5) must not create duplicate DB records."""
    test_file = tmp_dirs["pending"] / "test-dupe.md"
    content = "# Dupe Test\n\nThis content is identical.\n"
    test_file.write_text(content)

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", tmp_dirs["pending"]), \
         patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", tmp_dirs["processed"]), \
         patch("second_brain.nodes.ingestion_agent.FAILED_DIR", tmp_dirs["failed"]), \
         patch("second_brain.nodes.ingestion_agent.embed_text",
               AsyncMock(return_value=FAKE_EMBEDDING)), \
         patch("second_brain.nodes.ingestion_agent._generate_contextual_header",
               AsyncMock(return_value=FAKE_HEADER)):

        from second_brain.graphs.ingestion_graph import build_ingestion_graph
        graph = build_ingestion_graph()
        initial: IngestionState = {
            "files": ["test-dupe.md"],
            "in_progress": [],
            "processed": [],
            "retry_queue": [],
            "failed": [],
        }

        # First ingest
        await graph.ainvoke(initial)

        # Put file back in pending for second ingest
        (tmp_dirs["processed"] / "test-dupe.md").rename(tmp_dirs["pending"] / "test-dupe.md")

        # Second ingest — must skip embedding
        with patch("second_brain.nodes.ingestion_agent.embed_text", AsyncMock()) as mock_embed:
            await graph.ainvoke(initial)
            mock_embed.assert_not_called()

    # Only one DB record should exist
    with Session(engine) as session:
        docs = session.exec(
            select(IngestedDocument).where(IngestedDocument.filename == "test-dupe.md")
        ).all()
        assert len(docs) == 1, f"Expected 1 record, got {len(docs)}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_api_endpoint_ingest_file_returns_correct_response(tmp_dirs):
    """POST /ingest/file returns {numberOfFilePassed, failedFiles} correctly."""
    (tmp_dirs["pending"] / "test-api.md").write_text("# API Test\n\nTest content.\n")

    with patch("second_brain.nodes.ingestion_agent.PENDING_DOCS_DIR", tmp_dirs["pending"]), \
         patch("second_brain.nodes.ingestion_agent.PROCESSED_DIR", tmp_dirs["processed"]), \
         patch("second_brain.nodes.ingestion_agent.FAILED_DIR", tmp_dirs["failed"]), \
         patch("second_brain.api.routers.ingest.PENDING_DOCS_DIR", tmp_dirs["pending"]), \
         patch("second_brain.nodes.ingestion_agent.embed_text",
               AsyncMock(return_value=FAKE_EMBEDDING)), \
         patch("second_brain.nodes.ingestion_agent._generate_contextual_header",
               AsyncMock(return_value=FAKE_HEADER)):

        from httpx import AsyncClient, ASGITransport
        from second_brain.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/file")

    assert response.status_code == 200
    data = response.json()
    assert data["numberOfFilePassed"] == 1
    assert data["failedFiles"] == []
```

- [ ] **Step 2: Ensure Docker and migrations are ready**

```bash
docker compose up -d app_postgres
cd apps/backend && alembic upgrade head
```

Expected: migration output with `Running upgrade -> ...` and exit code 0.

- [ ] **Step 3: Run the integration tests**

```bash
pytest tests/integration/test_ingestion_graph.py -v -m integration
```

Expected: 3 tests PASSED.

- [ ] **Step 4: Run the complete test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASSED (unit + integration).

- [ ] **Step 5: Manual smoke test — the "done when" criterion**

```bash
# 1. Put a real markdown file in the pending folder
echo "# My Knowledge Note\n\nThis is a test of the ingestion pipeline." \
  > apps/backend/temp/pending-digest-docs/my-note.md

# 2. Start the backend (from apps/backend/)
uvicorn second_brain.main:app --reload --port 8000

# 3. In a separate terminal, call the endpoint
curl -s -X POST http://localhost:8000/ingest/file | python3 -m json.tool
```

Expected response:
```json
{
    "numberOfFilePassed": 1,
    "failedFiles": []
}
```

Also verify:
- `apps/backend/temp/processed/my-note.md` exists
- `apps/backend/temp/pending-digest-docs/my-note.md` is gone

- [ ] **Step 6: Commit**

```bash
git add apps/backend/tests/integration/__init__.py \
        apps/backend/tests/integration/test_ingestion_graph.py
git commit -m "test(ingestion): add integration tests for full ingestion pipeline"
```

---

## Self-Review Checklist

**Spec coverage:**

| Requirement | Covered by |
|-------------|-----------|
| Hybrid chunking: headings → blank lines → sentences | Task 2 (`chunking.py`) |
| Code fences never split | Task 2 (`_extract_code_fences`, `_merge_into_chunks` atomic check) |
| Article: target=512, max=1024, overlap=64 | Task 2 constants |
| Transcription: target=256, max=512, overlap=0 | Task 2 constants |
| Contextual retrieval headers via claude-haiku-4-5 | Task 5 (`_generate_contextual_header`) |
| Embedding via Ollama qwen3-embedding:0.6b | Task 1 (`embed_text`) |
| Content-type detection (article / transcription) | Task 2 (`detect_content_type`) |
| Heading path metadata: "H1 > H2 > H3" | Task 2 (`_split_by_headings`) |
| MD5 deduplication | Task 5 (`_compute_md5`, `_do_ingest` duplicate check) |
| Retry up to 3 total attempts | Task 5 (`MAX_RETRIES=3`, `ingestion_agent_node`) |
| in_progress crash-safe tracking | Task 4 (state field), Task 6 (`pick_file_node`) |
| Move to temp/processed/ on success | Task 5 (`_do_ingest`) |
| Move to temp/failed/ on terminal failure | Task 5 (`ingestion_agent_node`) |
| POST /ingest/file endpoint | Task 8 (`ingest_file`) |
| POST /ingest/url endpoint | Task 8 (`ingest_url`) |
| Tavily URL crawl → save as .md | Task 3 (`crawl_and_save`) |
| IngestFileResponse schema | Task 7 |
| IngestUrlRequest schema | Task 7 |
| Router registered in main.py | Task 9 |
| Integration test: file processed end-to-end | Task 10 |
| AC-7: retry 3× before terminal failure | Task 5 tests verify |
| AC-8: duplicate content hash skipped | Task 5 test + Task 10 integration test |

**Type consistency check:**
- `Chunk` dataclass: defined in `chunking.py`, used in `ingestion_agent.py` ✓
- `FailedFile` / `IngestionState`: defined in `graphs/state.py`, used in `nodes/ingestion_agent.py`, `graphs/ingestion_graph.py`, `api/routers/ingest.py` ✓
- `IngestFileResponse` / `IngestUrlRequest`: defined in `api/schemas.py`, used in `api/routers/ingest.py` ✓
- `embed_text(text: str) -> List[float]`: signature consistent across all usage ✓
- `chunk_document(content: str, source: str) -> List[Chunk]`: consistent ✓
- `crawl_and_save(url: str) -> Path`: consistent ✓
- `ingestion_agent_node(state: IngestionState) -> dict`: consistent ✓
- `ingestion_graph` module-level singleton: imported in `ingest.py`, also accessible via `build_ingestion_graph()` for tests ✓

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-16-ticket-3-ingestion.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review diffs between tasks, fast iteration via `superpowers:subagent-driven-development`

**2. Inline Execution** — execute tasks in this session with checkpoints via `superpowers:executing-plans`

Which approach?
