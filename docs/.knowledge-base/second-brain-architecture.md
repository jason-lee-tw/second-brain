# Second Brain Architecture

The approved system design for the "Second Brain" personal knowledge management system — API surface, tech stack, Docker network topology, the two LangGraph graphs, document chunking, memory, database schema, observability, and evaluation, plus the acceptance criteria that define "done."

## Key Concepts

- **Purpose**: a personal "Second Brain" knowledge management system — ingests local markdown files and web URLs, stores content for semantic retrieval, and maintains persistent memory of conversations and learned facts. Built with LangGraph multi-agent orchestration, evaluated with RAGAS metrics. Spec status: Approved, dated 2026-06-16.
- **API surface**:
  - `POST /query` — chat with the Second Brain. Request: `{"message": "string", "sessionId": "UUID7 or null"}`. Response: `{"answer", "sessionId", "confidence", "isUncertain", "conflictDetected", "conflictContext": []}`.
  - `POST /ingest/file` — processes pending markdown files from `temp/pending-digest-docs/`. Response: `{"numberOfFilePassed": N, "failedFiles": [...]}`.
  - `POST /ingest/url` — receives URL(s), crawls via Tavily, ingests the result as markdown.
  - Breaking change (Ticket 5): `conflictContext` changed from `list[str]` to `list[ConflictContext]`, each item `{"existing", "existing_id", "new"}`.
  - State→API field mapping: `isUncertain` ← `is_uncertain`; `conflictDetected` ← `awaiting_conflict_clarification`; `conflictContext` ← `conflict_context`.
  - `sessionId` null = new conversation; a UUID7 continues an existing session; it doubles as the LangGraph `threadId` and chat-history key.
  - Ingestion retries each file up to 3 times; files that exhaust retries move to `temp/failed/`.
- **Tech stack**: Python, FastAPI, LangGraph (orchestration), PostgreSQL + pgvector (via Docker), SQLModel + Alembic (ORM/migrations), Arize Phoenix/OTEL (observability), embedding model `qwen3-embedding:0.6b` via Ollama (`localhost:11434`, dim=1024), lightweight LLM `claude-haiku-4-5`, synthesis/eval LLM `claude-sonnet-4-6`, Tavily SDK (web search/crawl), Docker Compose (containerisation).

## System Architecture

- Two isolated Docker networks: `app_network` (backend, `app_postgres`) and `phoenix_network` (phoenix, `phoenix_postgres`) — fully isolated from each other; the backend has NO access to `phoenix_network`.
- The backend exports OTEL traces to Phoenix via gRPC on **host port 4317**; the Phoenix UI is exposed on host port 6006. The isolation is intentional — in production the backend must never have direct network access to Phoenix or its DB.
- Linux Docker hosts need `extra_hosts: ["host.docker.internal:host-gateway"]` on the backend service to reach the host port; Docker Desktop (Mac/Windows) provides this automatically.
- Two LangGraph graphs: Query Graph (`SecondBrainState`) and Ingestion Graph (`IngestionState`), both talk to `app_postgres` (tables: `chat_history`, `learned_facts` + embedding, `model_corrections` + embedding, `document_chunks` (pgvector), `ingested_documents`).
- Connection pool architecture: `db/pool.py` is the shared asyncpg pool singleton for pgvector queries; both `rag_retrieval` and `memory_retrieval_node` import `get_pgvector_pool()` from it — no redundant pools for the same DB. Two distinct pools coexist at the application level: asyncpg (pgvector reads) and psycopg3 (LangGraph checkpointing) — they cannot be merged, different drivers.

## Query Graph Flow

Agent responsibilities, in order:

1. `PIIRedactionNode` (inbound) — redacts `messages[-1].content`.
2. `MemoryRetrievalNode` (tool call) — cosine similarity search on `learned_facts` + `model_corrections`, populates `retrieved_memory` with top-k items.
3. `Orchestrator` (`claude-haiku-4-5`) — reads `messages[-1].content` + `retrieved_memory`, routes to `rag` / `web` / `both` / `neither` via LangGraph `Send` fan-out.
4. `RAG Retrieval Agent` (tool call, on `rag`/`both`) — embeds query via Ollama, cosine similarity on `document_chunks` pgvector, top-k=5 chunks with scores.
5. `Web Research Agent` (`claude-haiku-4-5`, on `web`/`both`) — Tavily search, top-3 results, rate-limited.
6. On `neither`: pass through (chat history + memory only).
7. `Synthesis` (`claude-sonnet-4-6`) — combines `rag_results` + `web_results` + trimmed `messages` + `retrieved_memory` → `final_answer` + `confidence` (0-1). Sets `is_uncertain=True` AND `awaiting_correction=True` when `confidence < 0.7`. `neither` routing uses chat history + memory only with confidence floor 0.5.
8. `PIIRedactionNode` (outbound) — redacts `final_answer` before appending to `messages`/persisting.
9. `Memory Agent` (`claude-haiku-4-5`, LangChain-Anthropic `with_structured_output(MemoryAgentOutput)`) — classifies via `MemoryCase` StrEnum into three cases: `FACT_EXTRACTION` (default — extracts self-referential facts), `CORRECTION` (when `awaiting_correction=True` — classifies as correction or new query, always resets `awaiting_correction=False`), `CONFLICT_RESOLUTION` (when `awaiting_conflict_clarification=True` — resolves conflict, also resets `awaiting_correction=False`; the two flags are mutually exclusive). Walks `messages` by type, no fixed indices.
10. On conflict detected: sets `awaiting_conflict_clarification=True`, surfaces the conflict in the response; else passes through.
11. `MemoryPersistenceNode` (tool call) — reads `fact_updates` + `correction_updates` from state; conflict-check reads via the asyncpg pool, writes via SQLModel sync `Session(engine)`; per-fact retry ×3 before failing the node; uses `settings.memory_conflict_threshold` (default 0.85, env `MEMORY_CONFLICT_THRESHOLD`); populates `ConflictContext` objects on conflict; Ollama calls raise on error (no silent degradation).
12. `Ingestion Agent` (`claude-haiku-4-5`, listed among agent roles) — chunks documents with a hybrid strategy, generates contextual retrieval headers per chunk, embeds via Ollama, upserts to `document_chunks`.

**LangGraph state type definitions (Query Graph)**:

- `RagResult` TypedDict: `content`, `score`, `chunk_index`, `metadata` (dict: source, heading_path, content_type).
- `WebResult` TypedDict: `title`, `url`, `content`.
- `MemoryItem` TypedDict: `id`, `fact`, `confidence`, `type: Literal["learned_fact", "model_correction"]`.
- `FactUpdate` TypedDict: `fact`, `confidence`, `conflicts_with: list[str]` (IDs of conflicting existing facts).
- `CorrectionUpdate` TypedDict: `original_answer` (prior AI response, found by walking messages by type), `correction`, `root_cause`.
- `ConflictContext` TypedDict: `existing` (text of existing fact), `existing_id` (UUID of existing learned_fact row), `new` (text of the proposed new fact).
- `MemoryCase` StrEnum: `FACT_EXTRACTION = "fact_extraction"`, `CORRECTION = "correction"`, `CONFLICT_RESOLUTION = "conflict_resolution"`.
- `MemoryAgentOutput` Pydantic BaseModel: `case: MemoryCase`, `fact_updates: list[FactUpdate] = []`, `correction_updates: list[CorrectionUpdate] = []`.
- `SecondBrainState` TypedDict: `session_id`, `messages` (trimmed view sent to LLMs; full history lives in the LangGraph checkpoint), `rag_results`, `web_results`, `retrieved_memory`, `routing_decision: Literal["rag","web","both","neither"]`, `final_answer`, `confidence`, `is_uncertain`. Five `NotRequired` fields (kept for backward compatibility with existing state-init code; must be initialised before memory nodes run): `awaiting_correction` (persisted across turns via checkpointing), `awaiting_conflict_clarification`, `conflict_context` (breaking change: was `list[str]`, now `list[ConflictContext]`), `fact_updates`, `correction_updates`.

## Ingestion Graph Flow

Input `files: list[str]` → move file to `in_progress` (checkpoint state) → Ingestion Agent (`claude-haiku-4-5`) chunk+embed+upsert to `document_chunks` → on success move to `processed`; on failure check `retry_count < 3`: yes → increment `retry_count`, move to `retry_queue`; no → move to `failed` (terminal) → loop while `retry_queue` is non-empty → return response `numberOfFilePassed` + `failedFiles`.

- `IngestionState` TypedDict: `files` (original input queue), `in_progress` (crash-safe tracking), `processed` (successfully ingested filenames), `retry_queue: list[FailedFile]` (`retry_count < 3`), `failed: list[FailedFile]` (terminal, `retry_count >= 3`).
- `FailedFile` TypedDict: `filename`, `error`, `retry_count`.
- URL ingestion flow: `POST /ingest/url` → Tavily crawl (extract page content) → save as `.md` in `temp/pending-digest-docs/` → trigger file ingestion (same Ingestion Graph).
- File folder structure: `temp/pending-digest-docs/` (drop files to ingest), `temp/processed/` (after success), `temp/failed/` (after 3 retries exhausted).

## Document Chunking Strategy

- Hybrid chunking: split on structural boundaries first (markdown headings H1/H2/H3), then blank lines between paragraphs, then sentence boundaries if a section still exceeds the max.
- Code fences are atomic — never split inside a ``` block.
- Header hierarchy (H1 > H2 > H3 path) is stored as chunk metadata for filtered retrieval.
- Token targets by content type: Markdown articles/notes — target 512, max 1024, overlap 64. Meeting transcriptions — target 256, max 512, overlap 0. Code fences — atomic, no max/overlap.
- Contextual Retrieval Headers: before embedding, each chunk gets a 50-100 token LLM-generated context header prepended, e.g. "This chunk is from [document title], section [H1 > H2], covering [topic summary]." Anthropic research is cited as showing this reduces retrieval failure rate by 49-67%.
- Document Deduplication: content hash (MD5) stored in `ingested_documents`; on ingestion, if the hash matches an existing record, the file is skipped; successful ingestion moves the file to `temp/processed/`.

## Memory System

- Learned Facts: auto-extracted from every user message when the user refers to themselves; embedded via `embed_text()` from `second_brain.services.embeddings` before storing (do NOT create a new embedding utility). Before storing, checked for conflicts via cosine similarity against existing facts using `settings.memory_conflict_threshold` (default 0.85). If a conflict is detected: `ConflictContext` objects are populated, `awaiting_conflict_clarification=True` is set, the conflict is surfaced in the response, and the graph waits for user clarification. After clarification, the Memory Agent classifies as `CONFLICT_RESOLUTION`; `MemoryPersistenceNode` deletes the conflicting IDs and writes the resolved fact. Per-fact retry up to 3 attempts before failing the entire `MemoryPersistenceNode`. Conflict-check reads via the asyncpg pool; writes via SQLModel sync `Session(engine)` — same pattern as `ingestion_agent.py`. Ollama unavailability in `memory_retrieval_node` fails hard (raises) — no silent degradation.
- State flag invariant: `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive. When the Memory Agent enters Case 3 (conflict clarification) it resets `awaiting_correction=False` before returning, preventing both flags being set simultaneously.
- Model Corrections: the Synthesis Agent sets both `is_uncertain=True` AND `awaiting_correction=True` when `confidence < 0.7`. `awaiting_correction` persists across turns via LangGraph checkpointing. When `awaiting_correction=True` and the user sends a correction: the Memory Agent walks `messages` by type to find the last `HumanMessage` and prior `AIMessage`, classifies as `CORRECTION`, extracts the root cause → `correction_updates`. When `awaiting_correction=True` and the user sends a non-correction: `awaiting_correction` is reset to `False` and normal fact extraction proceeds.
- PII guardrail: applied at two points — inbound (`messages[-1].content` before reaching any LLM node) and outbound (`final_answer` before being appended to `messages`/persisted to chat history). Scope: broad — names, emails, phone numbers, physical addresses, national IDs, financial data (card numbers, bank accounts), medical terms. Action: redact with typed placeholders `[NAME]`, `[EMAIL]`, `[PHONE]`, `[ADDRESS]`, `[ID]`, `[CARD]`, `[MEDICAL]`.

## Database Schema (app_postgres)

- `chat_history` — LangGraph session state / checkpoint store: `session_id` (UUID7, PK), `thread_data` (JSONB), `created_at`, `updated_at`.
- `document_chunks` — RAG document store: `id` (UUID, PK), `doc_id` (UUID, FK → `ingested_documents.id`), `content` (TEXT, chunk text with contextual header prepended), `embedding` (VECTOR(1024)), `chunk_index` (INT), `metadata` (JSONB: source, heading_path, content_type, char_count), `created_at`.
- `ingested_documents` — ingestion dedup: `id` (UUID, PK), `filename` (TEXT), `source_url` (TEXT, null for local files), `content_hash` (TEXT, MD5 of file content), `status` (TEXT: `'processed'`|`'failed'`), `ingested_at`.
- `learned_facts` — long-term memory: `id` (UUID, PK), `fact` (TEXT, PII-scrubbed), `embedding` (VECTOR(1024)), `source_session` (UUID7, FK → `chat_history.session_id`), `confidence` (FLOAT), `created_at`, `updated_at`.
- `model_corrections` — long-term memory: `id` (UUID, PK), `original_answer` (TEXT), `correction` (TEXT), `root_cause` (TEXT), `embedding` (VECTOR(1024), embeds the `correction` field — not `original_answer`), `source_session` (UUID7, FK → `chat_history.session_id`), `created_at`.
- ORM: SQLModel + Alembic. SQLModel models serve as both DB table definitions and FastAPI request/response schemas. Alembic handles all schema migrations. pgvector is supported via the `pgvector-python` package.

## Observability

Full distributed tracing across three levels per `/query` request — LLM call level (prompt/completion, token counts, latency), agent/node level (which agents ran, order, duration, routing decision), request level (end-to-end HTTP trace). Phoenix stores trace data in `phoenix_postgres` (isolated, only accessible within `phoenix_network`). The backend exports traces to Phoenix via the OTEL gRPC exporter targeting host port 4317 — the backend never joins `phoenix_network`. The Phoenix UI is exposed on host port 6006.

## Evaluation (Eval-Driven Development)

- Eval dataset: hybrid approach — Claude generates ~100 Q&A pairs from ingested documents, the user curates down to ~30-50 high-quality pairs; each pair includes a question, expected answer, and expected source chunk(s).
- Layer 1 (retrieval quality): Precision@k, Recall@k — measured via RAGAS `context_precision` and `context_recall`.
- Layer 2 (answer quality): Faithfulness (is the answer grounded in retrieved context?), Answer relevancy — measured via RAGAS with `claude-sonnet-4-6` as LLM judge.
- Baseline comparison: the same questions run through (1) a no-RAG baseline (Claude with no retrieval, system prompt only) and (2) the full RAG pipeline. Evidence requirement: RAGAS metrics must show measurable improvement of RAG over the no-RAG baseline.
- Confidence threshold calibration: `confidence < 0.7` is a starting point; during eval, precision/recall of uncertainty flags is measured against human-labelled ground truth and the threshold is adjusted based on evidence.
- When to run: offline / on-demand via a script, not part of CI.

## Acceptance Criteria

- AC-1: after a turn that extracts a user fact, `learned_facts` contains that fact with a valid embedding.
- AC-2: if `FactUpdate.conflicts_with` is non-empty after fact extraction, the API response includes a conflict notification and `awaiting_conflict_clarification=True` in session state.
- AC-3: given `awaiting_correction=True`, sending an unrelated new query resets `awaiting_correction=False` after the turn.
- AC-4: given `awaiting_correction=True` and a user correction, `model_corrections` contains the root cause and correction with a valid embedding.
- AC-5: PII in user messages is redacted before reaching any LLM node.
- AC-6: PII in `final_answer` is redacted before being persisted to `chat_history`.
- AC-7: a file in `temp/pending-digest-docs/` that fails ingestion is retried up to 3 times; on the 3rd failure it moves to `temp/failed/`.
- AC-8: a file already present in `ingested_documents` (matching content hash) is skipped on re-ingestion.
- AC-9: RAGAS `context_recall` and `faithfulness` for the full RAG pipeline are measurably higher than the no-RAG baseline on the curated eval dataset.
- AC-10: `/query` with a new `sessionId=null` creates a new LangGraph thread; subsequent requests with the returned UUID7 continue the same thread.

## Out of Scope / Future Ticket

"Unify embedding utility (D14)" — `services/embeddings.embed_text()` is the canonical embedding helper; `rag_retrieval.py` still contains a duplicate `_embed_query()` inline that bypasses `settings` and creates a per-call `httpx.AsyncClient()`. A future ticket will replace `_embed_query()` with `embed_text()`; that ticket should be planned before implementation.

## Open Questions

- **memory_conflict_threshold default**: this page states the default is `0.85`, but [[integration-testing]] and [[pgvector-embeddings]] describe the same conflict-check code path with the value bound as `0.95`. Unresolved — needs source verification.

## Sources

- Second Brain — System Design Spec — `docs/superpowers/specs/2026-06-16-second-brain-design.md`

## Related Topics

- [[memory-system]]
- [[database-schema]]
- [[query-graph]]
- [[query-workflow]]
- [[document-ingestion-pipeline]]
- [[evaluation-harness]]
- [[otel-phoenix-tracing]]
- [[pgvector-embeddings]]
- [[postgres-connection-pooling]]
- [[docker-compose]]
- [[multi-agent-architecture]]
- [[capstone-requirements]]
- [[project-requirements]]
- [[second-brain-requirements]]
- [[system-architecture]]
