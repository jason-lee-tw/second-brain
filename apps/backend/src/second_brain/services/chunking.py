import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

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


def _extract_code_fences(text: str) -> Tuple[str, Dict[str, str]]:
    """Replace ``` code fences with unique placeholders to protect them from
    splitting."""
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
    """Split on H1/H2/H3 boundaries. Returns [(heading_path, body_text)]."""
    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))

    if not matches:
        stripped = text.strip()
        return [("", stripped)] if stripped else []

    sections: List[Tuple[str, str]] = []
    heading_stack: List[str] = ["", "", ""]  # index 0=H1, 1=H2, 2=H3

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
            flush()
            result.append(para_restored)
            continue

        if para_tokens > max_tokens:
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

    chunks: List[Chunk] = []
    chunk_index = 0

    for heading_path, section_text in sections:
        section_restored = _restore_fences(section_text, placeholders)

        if count_tokens(section_restored) <= target:
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
            paragraphs = _split_by_paragraphs(section_text)
            merged = _merge_into_chunks(
                paragraphs, target, max_tokens, overlap, placeholders
            )
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
