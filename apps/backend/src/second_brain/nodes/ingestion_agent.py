import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from anthropic.types import TextBlock
from sqlmodel import Session, select

from second_brain.config import settings
from second_brain.db.models import DocumentChunk, IngestedDocument
from second_brain.db.session import engine
from second_brain.graphs.state import FailedFile, IngestionAgentOutput, IngestionState
from second_brain.services.chunking import Chunk, chunk_document
from second_brain.services.embeddings import embed_text

PENDING_DOCS_DIR = settings.pending_docs_dir
PROCESSED_DIR = Path("temp/processed")
FAILED_DIR = Path("temp/failed")

MAX_RETRIES = 3

_CHUNK_CONCURRENCY = 10
_CHUNK_SEMAPHORE = asyncio.Semaphore(_CHUNK_CONCURRENCY)

_anthropic = anthropic.AsyncAnthropic(
  api_key=settings.anthropic_api_key.get_secret_value()
)


async def shutdown() -> None:
  """Close the Anthropic async client. Called from the FastAPI lifespan."""
  await _anthropic.close()


def _sync_check_duplicate(content_hash: str) -> bool:
  with Session(engine) as session:
    existing = session.exec(
      select(IngestedDocument).where(IngestedDocument.content_hash == content_hash)
    ).first()
    return existing is not None


def _sync_write_results(
  doc_id: uuid.UUID,
  filename: str,
  source_url: str | None,
  content_hash: str,
  doc_chunks: list[DocumentChunk],
) -> None:
  with Session(engine) as session:
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
    for doc_chunk in doc_chunks:
      session.add(doc_chunk)
    session.commit()


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
  text_block = next((b for b in response.content if isinstance(b, TextBlock)), None)
  if text_block is None:
    raise ValueError(f"No TextBlock in Anthropic response: {response.content!r}")
  return text_block.text.strip()


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
    doc_id=doc_id,
    content=embedded_text,
    embedding=embedding,
    chunk_index=chunk.chunk_index,
    chunk_metadata=chunk.metadata,
  )


async def _do_ingest(filename: str, source_url: str | None = None) -> None:
  """Read, chunk, embed, and store one markdown file."""
  PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

  filepath = PENDING_DOCS_DIR / filename
  content = filepath.read_text(encoding="utf-8")
  content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

  is_duplicate = await asyncio.to_thread(_sync_check_duplicate, content_hash)
  if is_duplicate:
    filepath.rename(PROCESSED_DIR / filename)
    return

  doc_id = uuid.uuid4()
  chunks = chunk_document(content, source=filename)

  async def _bounded(chunk: Chunk) -> DocumentChunk:
    async with _CHUNK_SEMAPHORE:
      return await _process_one_chunk(chunk, filename, doc_id)

  doc_chunks = await asyncio.gather(*[_bounded(chunk) for chunk in chunks])

  await asyncio.to_thread(
    _sync_write_results,
    doc_id,
    filename,
    source_url,
    content_hash,
    list(doc_chunks),
  )

  filepath.rename(PROCESSED_DIR / filename)


async def ingestion_agent_node(state: IngestionState) -> IngestionAgentOutput:
  """LangGraph node: process in_progress, update state on success or failure."""
  if state["in_progress"] is None:
    raise ValueError("ingestion_agent_node called with empty in_progress")

  filename = state["in_progress"]

  retry_item = next(
    (f for f in state["retry_queue"] if f["filename"] == filename), None
  )
  current_count: int = retry_item["retry_count"] if retry_item else 0
  new_retry_queue = [f for f in state["retry_queue"] if f["filename"] != filename]

  source_url = state.get("source_urls", {}).get(filename)

  try:
    await _do_ingest(filename, source_url=source_url)

    return {
      "processed": state["processed"] + [filename],
      "in_progress": None,
      "retry_queue": new_retry_queue,
    }

  except Exception as exc:
    error_msg = str(exc)
    next_count = current_count + 1
    entry: FailedFile = {
      "filename": filename,
      "error": error_msg,
      "retry_count": next_count,
    }

    if next_count < MAX_RETRIES:
      return {
        "in_progress": None,
        "retry_queue": new_retry_queue + [entry],
        "failed": state["failed"],
      }

    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    src = PENDING_DOCS_DIR / filename
    if src.exists():
      src.rename(FAILED_DIR / filename)
    return {
      "in_progress": None,
      "retry_queue": new_retry_queue,
      "failed": state["failed"] + [entry],
    }
