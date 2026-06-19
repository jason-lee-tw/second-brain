# apps/backend/tests/unit/test_services/test_chunking.py
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
    assert "Root > Second" in paths
    assert "Root > First > Deep" in paths


# ── Sequential chunk index ─────────────────────────────────────────────────


def test_chunk_indices_are_sequential_starting_at_zero():
    content = "# A\n\nParagraph one.\n\n## B\n\nParagraph two.\n"
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
    for c in chunks:
        assert c.content.strip() == ""
