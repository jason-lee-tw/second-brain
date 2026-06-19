import re
from dataclasses import dataclass

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")

ARTICLE_TARGET = 512
ARTICLE_MAX = 1024
ARTICLE_OVERLAP = 64

TRANSCRIPTION_TARGET = 256
TRANSCRIPTION_MAX = 512
TRANSCRIPTION_OVERLAP = 0


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


def _extract_code_fences(text: str) -> tuple[str, dict[str, str]]:
    """Replace ``` code fences with unique placeholders to protect them from
    splitting."""
    matches = list(re.finditer(r"```[\s\S]*?```", text))
    placeholders = {f"__FENCE_{i}__": m.group(0) for i, m in enumerate(matches)}
    result = text
    for key, original in placeholders.items():
        result = result.replace(original, key, 1)
    return result, placeholders


def _restore_fences(text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Split on H1/H2/H3 boundaries. Returns [(heading_path, body_text)]."""
    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))

    if not matches:
        stripped = text.strip()
        return [("", stripped)] if stripped else []

    sections: list[tuple[str, str]] = []
    heading_stack: list[str] = ["", "", ""]  # index 0=H1, 1=H2, 2=H3

    pre = text[: matches[0].start()].strip()
    if pre:
        sections.append(("", pre))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()

        heading_stack[level - 1] = title
        for j in range(level, 3):
            heading_stack[j] = ""

        heading_path = " > ".join(h for h in heading_stack if h)

        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        if body:
            sections.append((heading_path, body))

    return sections


def _split_by_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_by_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _merge_into_chunks(
    paragraphs: list[str],
    max_tokens: int,
    overlap: int,
    placeholders: dict[str, str],
) -> list[str]:
    result: list[str] = []
    bucket: list[str] = []
    bucket_tokens = 0

    def flush(*, hard: bool = False) -> None:
        """Emit the current bucket. hard=True resets without overlap carry-over."""
        nonlocal bucket_tokens
        if not bucket:
            return
        result.append("\n\n".join(bucket))
        if not hard and overlap > 0:
            tail: list[str] = []
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

        if is_atomic:
            flush(hard=True)
            result.append(para_restored)
            continue

        para_tokens = count_tokens(para_restored)

        if para_tokens > max_tokens:
            flush(hard=True)
            for sentence in _split_by_sentences(para_restored):
                s_tokens = count_tokens(sentence)
                if bucket_tokens + s_tokens > max_tokens:
                    flush()
                bucket.append(sentence)
                bucket_tokens += s_tokens
        else:
            if bucket_tokens + para_tokens > max_tokens:
                flush()
            bucket.append(para_restored)
            bucket_tokens += para_tokens

    flush(hard=True)

    return result


def chunk_document(content: str, source: str) -> list[Chunk]:
    """Hybrid chunking: headings → paragraphs → sentences; code fences are atomic."""
    if not content.strip():
        return []

    content_type = detect_content_type(content)

    if content_type == "article":
        target, max_tokens, overlap = ARTICLE_TARGET, ARTICLE_MAX, ARTICLE_OVERLAP
    else:
        target, max_tokens, overlap = (
            TRANSCRIPTION_TARGET,
            TRANSCRIPTION_MAX,
            TRANSCRIPTION_OVERLAP,
        )

    modified, placeholders = _extract_code_fences(content)
    sections = _split_by_headings(modified)

    chunks: list[Chunk] = []
    chunk_index = 0

    def _make_chunk(text: str, idx: int, hp: str) -> Chunk:
        return Chunk(
            content=text,
            chunk_index=idx,
            metadata={
                "source": source,
                "heading_path": hp,
                "content_type": content_type,
                "char_count": len(text),
            },
        )

    for heading_path, section_text in sections:
        section_restored = _restore_fences(section_text, placeholders)

        if count_tokens(section_restored) <= target:
            chunks.append(_make_chunk(section_restored, chunk_index, heading_path))
            chunk_index += 1
        else:
            paragraphs = _split_by_paragraphs(section_text)
            merged = _merge_into_chunks(paragraphs, max_tokens, overlap, placeholders)
            for chunk_text in merged:
                chunks.append(_make_chunk(chunk_text, chunk_index, heading_path))
                chunk_index += 1

    return chunks
