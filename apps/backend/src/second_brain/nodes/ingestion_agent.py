import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

import anthropic
from sqlmodel import Session, select

from second_brain.config import settings
from second_brain.db.models import DocumentChunk, IngestedDocument
from second_brain.db.session import engine
from second_brain.graphs.state import FailedFile, IngestionState
from second_brain.services.chunking import Chunk, chunk_document
from second_brain.services.embeddings import embed_text

PENDING_DOCS_DIR = settings.pending_docs_dir
PROCESSED_DIR = settings.processed_dir
FAILED_DIR = settings.failed_dir

MAX_RETRIES = 3

_anthropic = anthropic.AsyncAnthropic(
    api_key=settings.anthropic_api_key.get_secret_value()
)


def _compute_md5(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


async def _generate_contextual_header(
    filename: str, heading_path: str, chunk_content: str
) -> str:
    """Generate a 50-100 token context header per chunk via claude-haiku-4-5."""
    prompt = (
        "Write a single-sentence context header (50-100 tokens) "
        "for this document chunk.\n"
        f"Document: {filename}\n"
        f"Section: {heading_path or 'N/A'}\n"
        f"Chunk preview: {chunk_content[:300]}\n\n"
        "Format exactly: "
        "'This chunk is from [filename], section [section], covering [brief topic].'\n"
        "Output only the header sentence, nothing else."
    )
    response = await _anthropic.messages.create(
        model=settings.ingestion_model,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def _process_one_chunk(
    chunk: Chunk, filename: str, doc_id: uuid.UUID
) -> DocumentChunk:
    header = await _generate_contextual_header(
        filename=filename,
        heading_path=chunk.metadata["heading_path"],
        chunk_content=chunk.content,
    )
    embedded_text = f"{header}\n\n{chunk.content}"
    embedding = await embed_text(embedded_text)
    return DocumentChunk(
        id=uuid.uuid4(),
        doc_id=doc_id,
        content=embedded_text,
        embedding=embedding,
        chunk_index=chunk.chunk_index,
        chunk_metadata=chunk.metadata,
        created_at=datetime.now(UTC),
    )


async def _do_ingest(
    filename: str, session: Session, source_url: str | None = None
) -> None:
    """Read, chunk, embed, and store one markdown file."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    filepath = PENDING_DOCS_DIR / filename
    content = filepath.read_text(encoding="utf-8")
    content_hash = _compute_md5(content)

    existing = session.exec(
        select(IngestedDocument).where(IngestedDocument.content_hash == content_hash)
    ).first()
    if existing:
        filepath.rename(PROCESSED_DIR / filename)
        return

    doc_id = uuid.uuid4()
    chunks = chunk_document(content, source=filename)

    # Insert IngestedDocument first and flush so the FK constraint is satisfied
    # before DocumentChunk rows (which reference doc_id) are inserted.
    session.add(
        IngestedDocument(
            id=doc_id,
            filename=filename,
            source_url=source_url,
            content_hash=content_hash,
            status="processed",
            ingested_at=datetime.now(UTC),
        )
    )
    session.flush()

    doc_chunks = await asyncio.gather(
        *[_process_one_chunk(chunk, filename, doc_id) for chunk in chunks]
    )
    for doc_chunk in doc_chunks:
        session.add(doc_chunk)

    session.commit()

    filepath.rename(PROCESSED_DIR / filename)


async def ingestion_agent_node(state: IngestionState) -> dict:
    """LangGraph node: process in_progress[0], update state on success or failure."""
    if not state["in_progress"]:
        raise ValueError("ingestion_agent_node called with empty in_progress")

    filename = state["in_progress"][0]

    retry_item = next(
        (f for f in state["retry_queue"] if f["filename"] == filename), None
    )
    current_count: int = retry_item["retry_count"] if retry_item else 0
    new_retry_queue = [f for f in state["retry_queue"] if f["filename"] != filename]

    source_url = state.get("source_urls", {}).get(filename)

    try:
        # ponytail: sync Session in async fn — swap to AsyncSession for multi-file load
        with Session(engine) as session:
            await _do_ingest(filename, session, source_url=source_url)

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
                "failed": state["failed"],
            }
        else:
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
