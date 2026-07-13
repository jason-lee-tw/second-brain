# Document Ingestion Pipeline

Files dropped in `temp/pending-digest-docs/` (or crawled from a URL) are hybrid-chunked, given a contextual header, embedded via Ollama, and upserted to pgvector by a dedicated `IngestionState` LangGraph graph, with MD5 dedup and a 3-attempt retry ceiling.

## Key Concepts

- **Goal**: the complete ingestion pipeline — hybrid chunking, Ollama embedding, pgvector storage, deduplication, retry logic, and both `POST /ingest/file` and `POST /ingest/url` endpoints.
- **High-level flow**: a file is moved to `in_progress`, checkpointed, then processed by the `Ingestion Agent` node (model `claude-haiku-4-5` for header generation): (1) hybrid-chunk by heading → paragraph → sentence, (2) generate a 50–100 token contextual header per chunk, (3) embed header+chunk via Ollama `qwen3-embedding:0.6b`, (4) upsert to `document_chunks`. On success the file moves `in_progress` → `processed/`. On failure, `retry_count < 3` sends it back to `retry_queue`; otherwise it moves to `failed/` as a terminal state. The graph loops while `files` or `retry_queue` is non-empty.
- **URL ingestion** (`POST /ingest/url`, `urls: list[str]`): Tavily crawl extracts page content, saved as a `.md` file under `temp/pending-digest-docs/`, which then triggers the identical file-ingestion flow (same graph).
- **Tech stack**: Python, FastAPI, LangGraph, SQLModel, PostgreSQL + pgvector, Ollama (`qwen3-embedding:0.6b`), `claude-haiku-4-5` (contextual headers), `tavily-python`, `tiktoken` (`cl100k_base`), `httpx`.
- **Two independent LangGraph graphs**: `IngestionState` (this pipeline) and the query-side `SecondBrainState` share the same database but never share runtime state — separating them keeps state schemas clean.
- **Prerequisites**: `IngestedDocument`/`DocumentChunk` SQLModel models, SQLAlchemy `engine`, and FastAPI `app` already exist from infrastructure setup; `second_brain` package is installable from `src/`.

## Chunking Strategy

- `Chunk` dataclass: `content: str`, `chunk_index: int`, `metadata: dict` (`source`, `heading_path`, `content_type`, `char_count`).
- `count_tokens(text)` uses `tiktoken.get_encoding("cl100k_base")`.
- `detect_content_type(text)` → `"article"` if any markdown H1–H3 heading is present, else `"transcription"`.
- Token budgets: article — target 512, max 1024, overlap 64; transcription — target 256, max 512, overlap 0.
- Code fences (` ``` ... ``` `) are protected before any splitting — replaced with `__FENCE_N__` placeholders, guaranteeing a fenced block is never split across chunks and always forms its own atomic unit if its paragraph overflows.
- Split order: (1) headings (H1–H3, tracked via a 3-slot `heading_stack`, building `heading_path` as `"H1 > H2 > H3"`, resetting deeper levels when a shallower heading recurs), (2) paragraphs (blank-line split), (3) sentence boundaries (`(?<=[.!?])\s+`) as a fallback only when a paragraph itself exceeds `max_tokens`.
- Bucket merging carries trailing paragraphs/sentences (up to `overlap` tokens) into the next chunk when `overlap > 0`; atomic fenced paragraphs are always flushed as their own chunk.
- `chunk_document(content, source)` orchestrates the above; empty content returns `[]`; `chunk_index` is sequential from 0 across the whole document.
- `MAX_RETRIES = 3` (total attempts before terminal failure) is also defined in the chunking module and reused by the ingestion agent.

## Deduplication, Embedding, and Retry Handling

- **Deduplication**: MD5 hash (`_compute_md5`) of the raw file content is compared against `IngestedDocument.content_hash`. A match skips chunking/embedding entirely — the file is just moved to `processed/`.
- **Contextual header**: for new (non-duplicate) documents, each chunk gets an LLM-generated header via `claude-haiku-4-5`, 50–100 tokens, single sentence, exact template `"This chunk is from [filename/title], section [heading_path], covering [brief topic]."`.
- **Embedding**: `header + "\n\n" + chunk.content` is embedded via Ollama `qwen3-embedding:0.6b` into a `VECTOR(1024)` column (`embed_text` calls Ollama's `/api/embeddings`, `OLLAMA_BASE_URL` default `http://localhost:11434`, must return exactly 1024 floats, propagates `httpx.HTTPStatusError` rather than swallowing it).
- **Storage**: each `DocumentChunk` is written with a shared `doc_id` (uuid4) across all chunks of a document, storing `heading_path` and `content_type` inside the chunk's JSONB `metadata` column (Python attribute `chunk_metadata`). After all chunks are added, an `IngestedDocument` row is committed with `status="processed"`.
- **Retry/failure**: on exception, `retry_count` increments; if the new count is `< MAX_RETRIES` (3) the file re-enters `retry_queue` (non-terminal); once it reaches 3, the file moves `pending-digest-docs/` → `failed/` (terminal) and is recorded in `state["failed"]` instead of `retry_queue`.
- **Crash-safety**: `in_progress` holds at most one file at a time, so an in-flight file's state survives a crash and can be resumed/retried rather than silently lost.

## Graph and API Shape

- `IngestionState` TypedDict fields: `files` (original queue), `in_progress` (0 or 1 item), `processed`, `retry_queue` (list of `FailedFile`, `retry_count < 3`), `failed` (list of `FailedFile`, `retry_count >= 3`). `FailedFile`: `filename`, `error`, `retry_count`.
- Graph nodes: `pick_file` (moves next filename — prioritizing `files[]` over `retry_queue` — into `in_progress`) → `ingest` (runs the ingestion agent) → conditional edge back to `pick_file` while `files` or `retry_queue` is non-empty, else `END`.
- `POST /ingest/file`: globs `*.md` in `temp/pending-digest-docs/`; empty directory returns `IngestFileResponse(numberOfFilePassed=0, failedFiles=[])` immediately without invoking the graph; otherwise runs the graph and maps `numberOfFilePassed=len(final_state["processed"])`, `failedFiles=[f["filename"] for f in final_state["failed"]]`.
- `POST /ingest/url`: sequentially calls `crawl_and_save(url)` per URL (via Tavily, `client.extract(urls=[url])`, deterministic slug filename from the URL, not random), folds resulting filenames into the same graph invocation and response mapping.
- Response schema is intentionally camelCase (`numberOfFilePassed`, `failedFiles`), not snake_case.
- Integration coverage requires a running Postgres with migrations applied; only Ollama embedding and the Anthropic header call are mocked — chunking, graph routing, and DB writes run for real, verifying end-to-end pending→processed moves, dedup survival across two real ingests, and the live `/ingest/file` HTTP response shape.

## Related: JSONB Metadata Column Read Path

- The `metadata` JSONB column populated on each `DocumentChunk` during ingestion (holding `heading_path` and `content_type`) is read back during query-time RAG retrieval. `asyncpg` does not auto-decode `jsonb` columns by default, which previously caused a `ValueError` when reading this ingestion-written metadata back out. The fix registers a JSONB type codec (`conn.set_type_codec("jsonb", ...)`) alongside the pgvector codec on every pooled connection — a retrieval-pool concern, not a change to the ingestion write path itself.

## Sources

- [Document Ingestion Pipeline — Implementation Plan] — `docs/superpowers/plans/2026-06-16-ticket-3-ingestion.md`
- [Workflow Design — Data Ingestion Workflow] — `docs/business/004-workflow-design.md`
- [Fix asyncpg JSONB Codec Registration Implementation Plan] — `docs/superpowers/plans/2026-06-25-fix-asyncpg-jsonb-codec.md`

## Related Topics

- [[query-workflow]]
- [[query-graph]]
- [[asyncpg-jsonb-codec]]
- [[pgvector-embeddings]]
- [[database-schema]]
- [[second-brain-architecture]]
- [[capstone-requirements]]
- [[implementation-plan]]
- [[second-brain-requirements]]
- [[type-checking]]
