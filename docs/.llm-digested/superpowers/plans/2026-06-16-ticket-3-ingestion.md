# Document Ingestion Pipeline — Implementation Plan

Source: docs/superpowers/plans/2026-06-16-ticket-3-ingestion.md
Primary-Topic: document-ingestion-pipeline
Secondary-Topics: langgraph-architecture, hybrid-chunking-strategy

## Key Concepts

- **Goal**: build the complete document ingestion pipeline — hybrid chunking, Ollama embedding, pgvector storage, deduplication, retry logic, and both `POST /ingest/file` and `POST /ingest/url` endpoints.
- **High-level architecture**: files dropped in `temp/pending-digest-docs/` are processed by a LangGraph graph (`IngestionState`) that: chunks documents with a hybrid strategy (headings → paragraphs → sentences), prepends an LLM-generated contextual header per chunk, embeds via Ollama `qwen3-embedding:0.6b`, and upserts to PostgreSQL pgvector. The graph retries failed files up to 3 total attempts, moving terminal failures to `temp/failed/` and successes to `temp/processed/`. URL ingestion first crawls via Tavily to save a markdown file, then feeds the same graph.
- **Tech stack used**: Python, FastAPI, LangGraph, SQLModel, PostgreSQL + pgvector, Ollama (`qwen3-embedding:0.6b`), `claude-haiku-4-5` (for contextual headers), `tavily-python`, `tiktoken` (`cl100k_base` encoding), `httpx`.
- **Prerequisites (Ticket 1, already exist)**: `apps/backend/src/second_brain/db/models.py` with `IngestedDocument` and `DocumentChunk` SQLModel models; `apps/backend/src/second_brain/db/session.py` with SQLAlchemy `engine`; `apps/backend/src/second_brain/main.py` with FastAPI `app`; `second_brain` package installable from `src/`.
- **Recommended execution methods**: `superpowers:subagent-driven-development` (dispatch a fresh subagent per task, review diffs between tasks) or `superpowers:executing-plans` (execute tasks inline with checkpoints). Plan uses checkbox syntax for task tracking.

### File map (created/modified)

- `services/embeddings.py` — Ollama HTTP embed call.
- `services/chunking.py` — hybrid chunker (`Chunk` dataclass, `chunk_document`).
- `services/tavily.py` — Tavily URL crawl → markdown file.
- `graphs/state.py` — `IngestionState`, `FailedFile` TypedDicts.
- `nodes/ingestion_agent.py` — LangGraph node: read → dedup → chunk → header → embed → upsert.
- `graphs/ingestion_graph.py` — LangGraph graph: `pick_file` → `ingest` → route loop.
- `api/schemas.py` — `IngestFileResponse`, `IngestUrlRequest` Pydantic models.
- `api/routers/ingest.py` — `POST /ingest/file` and `POST /ingest/url`.
- `main.py` — modified to register the ingest router.
- Corresponding unit tests under `apps/backend/tests/unit/` for every module above, plus one integration test `apps/backend/tests/integration/test_ingestion_graph.py`.
- All `pytest` commands in the plan are run from `apps/backend/`.

### Task 1 — Embedding service (`services/embeddings.py`)

- `embed_text(text: str) -> List[float]` calls Ollama's `/api/embeddings` endpoint via `httpx.AsyncClient(timeout=60.0)`.
- Config: `OLLAMA_BASE_URL` env var (default `http://localhost:11434`), `EMBEDDING_MODEL = "qwen3-embedding:0.6b"`.
- POST payload: `{"model": EMBEDDING_MODEL, "prompt": text}`; response parsed as `response.json()["embedding"]`.
- Must return exactly 1024 floats.
- Must propagate `httpx.HTTPStatusError` rather than swallowing it (`response.raise_for_status()` is called).
- Tests: returns 1024-length float list; posts to correct endpoint/payload; propagates HTTP errors.

### Task 2 — Hybrid chunking service (`services/chunking.py`)

- `Chunk` dataclass: `content: str`, `chunk_index: int`, `metadata: dict` (keys: `source`, `heading_path`, `content_type`, `char_count`).
- `count_tokens(text)` uses `tiktoken.get_encoding("cl100k_base")`.
- `detect_content_type(text) -> "article" | "transcription"`: `"article"` if any markdown H1–H3 heading (`^#{1,3}\s`) is present, else `"transcription"`.
- Token budgets by content type:
  - Article: target=512, max=1024, overlap=64.
  - Transcription: target=256, max=512, overlap=0.
- `MAX_RETRIES = 3` constant also lives in this module (total attempts before terminal failure — later duplicated/used in `ingestion_agent.py`).
- Code-fence protection: ``` ```...``` ``` blocks are replaced with unique `__FENCE_N__` placeholders before any splitting (`_extract_code_fences`/`_restore_fences`), guaranteeing a fence is never split across chunks and always forms its own atomic unit when its containing paragraph overflows.
- Heading split (`_split_by_headings`): splits on H1–H3 boundaries, tracks a 3-slot `heading_stack` (H1/H2/H3), builds `heading_path` as `"H1 > H2 > H3"`, resets deeper levels when a shallower heading recurs (e.g. new H2 clears any H3), and captures pre-heading content under an empty heading_path.
- Paragraph split (`_split_by_paragraphs`): split on blank lines (`\n\s*\n`).
- Sentence split (`_split_by_sentences`): split on `(?<=[.!?])\s+`, used only as a fallback when a paragraph itself exceeds `max_tokens`.
- `_merge_into_chunks`: merges paragraph-level units into token-bounded buckets; atomic (fenced) paragraphs are flushed and emitted as their own chunk; oversized non-fence paragraphs fall back to sentence-level splitting; on bucket overflow, `flush_with_overlap` carries trailing paragraphs/sentences (up to `overlap` tokens) into the next bucket, when `overlap > 0`.
- `chunk_document(content, source) -> List[Chunk]`: top-level orchestration — empty content returns `[]`; detects content type; extracts fences; splits by heading; for each heading section, emits one chunk if it fits under `target` tokens, otherwise paragraph/sentence-merges it; assigns sequential `chunk_index` starting at 0 across the whole document.
- Tests cover: content-type detection (H1/H2 → article, no headings → transcription), Chunk object list return type, H1/nested/reset heading-path metadata, sequential chunk indices from 0, `source`/`char_count`/`content_type` metadata fields, code fence atomicity (single fence, multiple fences), pre-heading content capture, and safe handling of empty content.

### Task 3 — Tavily URL crawl service (`services/tavily.py`)

- Uses `tavily.AsyncTavilyClient`; `TAVILY_API_KEY` env var; `PENDING_DOCS_DIR = Path("temp/pending-digest-docs")`.
- `_url_to_slug(url)`: strips `https?://`, replaces non-alphanumerics with `-`, trims to 80 chars — used to build a deterministic (not random) filename from the URL.
- `crawl_url(url) -> str`: calls `client.extract(urls=[url])`, returns `results[0]["raw_content"]`; raises `ValueError("...no content...")` when Tavily returns an empty `results` list.
- `crawl_and_save(url) -> Path`: calls `crawl_url`, writes content to `PENDING_DOCS_DIR/<slug>.md` (creating the dir if needed), returns the saved `Path`.
- Tests: `crawl_url` returns raw content; raises `ValueError` on empty results; `crawl_and_save` writes a `.md` file and returns an existing path; filename is derived from the URL (contains recognizable URL fragments, e.g. "example"), not random.

### Task 4 — `IngestionState` / `FailedFile` TypedDicts (`graphs/state.py`)

- `FailedFile` TypedDict: `filename: str`, `error: str`, `retry_count: int`.
- `IngestionState` TypedDict: `files: list[str]` (original input queue, first-attempt files), `in_progress: list[str]` (crash-safe in-flight tracking, holds 0 or 1 item), `processed: list[str]` (successfully ingested filenames), `retry_queue: list[FailedFile]` (retry_count < 3), `failed: list[FailedFile]` (terminal failures, retry_count >= 3).
- This is a **separate** LangGraph state schema from the query-side `SecondBrainState` — the two graphs share no runtime state (documented project-wide convention).

### Task 5 — Ingestion agent node (`nodes/ingestion_agent.py`)

- Processes exactly one file per call, taken from `state["in_progress"][0]`.
- Pipeline inside `_do_ingest`: read file from `PENDING_DOCS_DIR`; compute MD5 of raw content (`_compute_md5`); **deduplication** — query `IngestedDocument` by `content_hash`; if a match exists, skip embedding entirely and just move the file to `PROCESSED_DIR`; otherwise chunk via `chunk_document`, and for each chunk: generate a contextual header via `_generate_contextual_header` (calls `claude-haiku-4-5` through `anthropic.AsyncAnthropic()`, prompting for a 50–100 token single-sentence header in the exact format `"This chunk is from [filename], section [section], covering [brief topic]."`), then embed `header + "\n\n" + chunk.content` via `embed_text`, then `session.add(DocumentChunk(...))` with a shared `doc_id` (uuid4) across all chunks of that document. After all chunks: `session.add(IngestedDocument(...))` with `status="processed"`, commit, then move the file from `PENDING_DOCS_DIR` to `PROCESSED_DIR`.
- Retry/failure handling in `ingestion_agent_node`: looks up any existing `FailedFile` entry for this filename in `state["retry_queue"]` to get `current_count` (0 if none); removes it from the queue (it will be re-added on repeat failure); on success returns updated `processed`/cleared `in_progress`/pruned `retry_queue`. On exception: increments `retry_count`; if `next_count < MAX_RETRIES` (3), appends a `FailedFile` back into `retry_queue` (non-terminal); if `next_count >= MAX_RETRIES`, moves the file from `PENDING_DOCS_DIR` to `FAILED_DIR` (terminal) and appends to `state["failed"]` instead.
- Module-level constants: `PENDING_DOCS_DIR = Path("temp/pending-digest-docs")`, `PROCESSED_DIR = Path("temp/processed")`, `FAILED_DIR = Path("temp/failed")`, `MAX_RETRIES = 3`.
- Tests: successful ingest moves file pending→processed and adds to `processed` list; duplicate content hash is skipped without calling `embed_text` and file still moves to processed; first failure increments retry_count to 1 and lands in `retry_queue` (not `failed`); a failure when already at retry_count=2 reaches the MAX_RETRIES=3 threshold, moves file to `FAILED_DIR`, and lands in `failed` (removed from `retry_queue`).

### Task 6 — Ingestion graph (`graphs/ingestion_graph.py`)

- Two nodes: `pick_file` (moves the next pending-or-retry filename into `in_progress`; prioritizes `files[]` over `retry_queue`; does NOT remove the item from `retry_queue` itself — `ingestion_agent_node` does that after the attempt to preserve retry metadata) and `ingest` (calls `ingestion_agent_node`).
- `_route_after_ingest`: conditional edge after `ingest` — loops back to `pick_file` while `files` or `retry_queue` is non-empty, otherwise routes to `END`.
- `build_ingestion_graph()` wires `StateGraph(IngestionState)` with entry point `pick_file`, edge `pick_file → ingest`, conditional edge from `ingest` back to `pick_file` or to `END`.
- Module-level singleton `ingestion_graph = build_ingestion_graph()` is what the API router imports; `build_ingestion_graph()` itself is exposed separately for tests.
- Tests: processes a single file end-to-end; processes multiple files sequentially; retries a file that fails once then succeeds on the second attempt (verifying `call_count == 2`); terminates (does not loop forever) once `files` and `retry_queue` are both empty.

### Task 7 — API schemas (`api/schemas.py`)

- `IngestFileResponse(BaseModel)`: `numberOfFilePassed: int`, `failedFiles: list[str]` — field names are camelCase by design (not snake_case), and `model_dump()` must serialize using those exact camelCase keys.
- `IngestUrlRequest(BaseModel)`: `urls: list[str]` — required field; omitting it raises `pydantic.ValidationError`.

### Task 8 — Ingest router (`api/routers/ingest.py`)

- `router = APIRouter(prefix="/ingest", tags=["ingest"])`; module-level `PENDING_DOCS_DIR = Path("temp/pending-digest-docs")` (patchable in tests).
- `POST /ingest/file`: ensures `PENDING_DOCS_DIR` exists, globs `*.md` filenames; if none found returns `IngestFileResponse(numberOfFilePassed=0, failedFiles=[])` immediately without invoking the graph; otherwise builds an initial `IngestionState` with `files=<discovered filenames>` and all other fields empty, calls `await ingestion_graph.ainvoke(initial_state)`, and maps the final state to the response (`numberOfFilePassed=len(final_state["processed"])`, `failedFiles=[f["filename"] for f in final_state["failed"]]`).
- `POST /ingest/url` (body: `IngestUrlRequest`): sequentially calls `crawl_and_save(url)` for each URL in `request.urls`, collects resulting filenames, then runs the same ingestion graph invocation and response mapping as `/ingest/file`. If no URLs produced saved files, returns the zero response immediately.
- Tests: empty pending directory → `numberOfFilePassed=0`; discovers `.md` files and invokes the graph with them; reports failed filenames pulled from the final graph state's `failed` list; `/ingest/url` calls `crawl_and_save` with the exact URL and folds the crawled file into the graph invocation.

### Task 9 — Register router in `main.py`

- Pure FastAPI wiring, no TDD: add `from second_brain.api.routers.ingest import router as ingest_router` alongside other router imports, and `app.include_router(ingest_router)` alongside other `include_router` calls.
- Verification: a Python snippet confirms `/ingest/file` and `/ingest/url` appear in `[r.path for r in app.routes]`; then the full unit suite (`pytest tests/unit/ -v`) must still pass.

### Task 10 — Integration test (`tests/integration/test_ingestion_graph.py`)

- Exercises the real LangGraph graph and real chunking logic end-to-end; only Ollama (`embed_text`) and Anthropic (`_generate_contextual_header`) are mocked — everything else (chunking, graph routing, DB writes) runs for real.
- Requires PostgreSQL running (`docker compose up -d app_postgres`) and Alembic migrations applied (`alembic upgrade head`); tests are marked `@pytest.mark.integration`.
- `clean_db` autouse fixture deletes any `DocumentChunk`/`IngestedDocument` rows whose filename starts with `"test-"` after each test, to avoid cross-test DB contamination.
- `test_full_ingest_file_success`: verifies the file moves pending→processed, `IngestedDocument.status == "processed"` with a non-null `content_hash`, at least one `DocumentChunk` created with a 1024-dim embedding, and the contextual header text present inside stored chunk content.
- `test_duplicate_file_is_skipped_on_reingest`: ingests the same file twice (moving it back to pending in between); the second pass must not call `embed_text` and only one `IngestedDocument` row must exist for that filename — proves MD5 dedup survives a real graph run.
- `test_api_endpoint_ingest_file_returns_correct_response`: drives the real FastAPI app via `httpx.AsyncClient`/`ASGITransport`, hitting `POST /ingest/file` for real and checking the JSON response shape.
- Manual "done when" smoke test: write a real `.md` file into `temp/pending-digest-docs/`, run `uvicorn second_brain.main:app --reload --port 8000`, `curl -X POST http://localhost:8000/ingest/file`, and confirm the JSON response plus that the file physically moved from `pending-digest-docs/` to `processed/`.

### Self-review / spec coverage table (from the plan's closing checklist)

Explicitly cross-references every requirement to its implementing task, including: hybrid chunking (headings→blank lines→sentences), code fences never split, article/transcription token budgets, contextual retrieval headers via `claude-haiku-4-5`, Ollama `qwen3-embedding:0.6b` embedding, content-type detection, heading-path metadata format, MD5 deduplication, 3-attempt retry ceiling, crash-safe `in_progress` tracking, processed/failed directory moves, both ingest endpoints, Tavily crawl-to-markdown, both Pydantic schemas, router registration, and the integration test. Also lists a "type consistency check" confirming `Chunk`, `FailedFile`/`IngestionState`, `IngestFileResponse`/`IngestUrlRequest`, and function signatures (`embed_text`, `chunk_document`, `crawl_and_save`, `ingestion_agent_node`) are used consistently across every module that imports them, and that `ingestion_graph` is both a module-level singleton and available via `build_ingestion_graph()` for tests.
