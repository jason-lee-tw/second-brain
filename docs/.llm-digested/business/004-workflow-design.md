# Workflow Design

Source: docs/business/004-workflow-design.md
Primary-Topic: query-workflow
Secondary-Topics: ingestion-workflow, memory-workflow

## Key Concepts

- Two independent LangGraph graphs share the same database but never share runtime state: `SecondBrainState` (Query Graph, triggered by `POST /query`) and `IngestionState` (Ingestion Graph, triggered by `POST /ingest/file` and `POST /ingest/url`).

### 1. User Query Workflow (`POST /query`, message + sessionId)

- Step B — `PIIRedactionNode` (inbound, rule-based): redacts `messages[-1].content` before any LLM sees it, replacing PII with typed placeholders: NAME, EMAIL, PHONE, ADDRESS, ID, CARD, MEDICAL.
- Step C — `MemoryRetrievalNode` (tool call): cosine similarity search over `learned_facts` + `model_corrections`, populates `retrieved_memory`.
- Step D — `Orchestrator` (model `claude-haiku-4-5`): reads `messages[-1]` + `retrieved_memory`, routes via LangGraph `Send` fan-out to one or more of: `rag`, `web`, `both`, `neither`.
- Step E — `RAG Retrieval` (tool call): embeds the query via Ollama, pgvector cosine similarity top-k=5 over `document_chunks`.
- Step F — `Web Research` (model `claude-haiku-4-5`): Tavily search, top-3 results.
- Step G — pass-through path when orchestrator routes to `neither` (chat history + memory only, no RAG/web).
- Step H — `Synthesis` (model `claude-sonnet-4-6`): combines `rag_results` + `web_results` + `retrieved_memory` + `messages` to produce `final_answer` + `confidence` (0–1 scale).
  - If `confidence < 0.7`: sets `is_uncertain=True` and `awaiting_correction=True`.
  - If `confidence >= 0.7`: sets `is_uncertain=False`.
- Step I — `PIIRedactionNode` (outbound, rule-based): redacts `final_answer` before it's appended to `messages` / chat history.
- Step J — `Memory Agent` (model `claude-haiku-4-5`): uses `with_structured_output(MemoryAgentOutput)`, classifies the turn via `MemoryCase` into one of four branches:
  - `FACT_EXTRACTION` (default case): extracts self-referential facts from the user message → `fact_updates`.
  - `CORRECTION` (when `awaiting_correction=True` and the user's message is actually a correction): walks `messages` by type to extract `correction` + `root_cause`, produces `correction_updates`, resets `awaiting_correction=False`.
  - `CORRECTION` (when `awaiting_correction=True` but the user's next message is an unrelated query): resets `awaiting_correction=False` and falls back to normal fact extraction.
  - `CONFLICT_RESOLUTION` (when `awaiting_conflict_clarification=True`): resolves the conflict and resets `awaiting_correction=False`.
- Step K — `MemoryPersistenceNode` (tool call): writes `fact_updates` → `learned_facts` table, writes `correction_updates` → `model_corrections` table, generates embeddings via Ollama, retries each fact write up to 3 times.
  - If a conflict is detected (cosine similarity > 0.85 against existing facts): sets `awaiting_conflict_clarification=True`, populates a `ConflictContext`, and surfaces the conflict in the response.
  - If no conflict: passes through.
- Final response (`N`): returns `answer` + `sessionId` + `confidence` + `isUncertain` + `conflictDetected` + `conflictContext`.

**Agent responsibility table** (name → model → role):
- PIIRedactionNode (in) — rule-based — redact PII from `messages[-1]` before any LLM sees it.
- MemoryRetrievalNode — tool call — cosine similarity on `learned_facts` + `model_corrections`, populates `retrieved_memory`.
- Orchestrator — `claude-haiku-4-5` — routes to rag/web/both/neither via LangGraph `Send` fan-out.
- RAG Retrieval — tool call — embed query via Ollama, pgvector top-k=5 from `document_chunks`.
- Web Research — `claude-haiku-4-5` — Tavily search, top-3 results.
- Synthesis — `claude-sonnet-4-6` — produces `final_answer` + `confidence`; sets uncertainty flags when `confidence < 0.7`.
- PIIRedactionNode (out) — rule-based — redact `final_answer` before persisting to chat history.
- Memory Agent — `claude-haiku-4-5` — classifies turn as FACT_EXTRACTION / CORRECTION / CONFLICT_RESOLUTION, outputs structured `MemoryAgentOutput`.
- MemoryPersistenceNode — tool call — writes facts + corrections with embeddings; conflict-checks via cosine similarity (threshold 0.85).

**State flag invariants:**
- `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive.
- Entering `CONFLICT_RESOLUTION` always resets `awaiting_correction=False`.
- Session continuity: `sessionId` is the LangGraph `threadId`. `null` = start a new thread; a returning UUID7 continues the same thread via `AsyncPostgresSaver` checkpointing.

### 2. Data Ingestion Workflow

**File Ingestion Flow** (`POST /ingest/file`, or files produced by URL ingestion):
- Move file to `in_progress`, checkpoint state.
- `Ingestion Agent` (model `claude-haiku-4-5`): (1) hybrid-chunks by heading / paragraph / sentence, (2) generates a 50–100 token contextual header per chunk, (3) embeds via Ollama `qwen3-embedding:0.6b`, (4) upserts to `document_chunks`.
- On success: move file `in_progress` → `processed` (`temp/processed/`).
- On failure: check `retry_count < 3`.
  - If yes: increment `retry_count`, move to `retry_queue`.
  - If no (retries exhausted): move to `failed` (`temp/failed/`) — terminal state.
- If `retry_queue` is non-empty, loop back to the "move to in_progress" step; otherwise return final response: `numberOfFilePassed` + `failedFiles`.

**URL Ingestion Flow** (`POST /ingest/url`, urls: list[str]):
- Tavily crawl extracts page content.
- Content saved as `.md` file under `temp/pending-digest-docs/`.
- Triggers the same file-ingestion flow described above (same Ingestion Graph).

**Document Chunking Strategy** (used by the Ingestion Agent):
- Content-type branching:
  - Code fence → atomic chunk, never split inside a ``` fenced block.
  - Meeting transcript → split at sentence boundaries, target 256 tokens, max 512, overlap 0.
  - Markdown article/note → split order is (1) H1/H2/H3 headings, (2) blank lines between paragraphs, (3) sentence boundaries if a section still exceeds max; target 512 tokens, max 1024, overlap 64.
- Deduplication check: MD5 hash of the document compared against `ingested_documents`; duplicates are skipped entirely (no chunking/embedding work performed).
- For new (non-duplicate) documents: generate a contextual header per chunk (50–100 tokens, via `claude-haiku-4-5`) with template "This chunk is from [title], section [H1>H2], covering [topic]".
- Embed chunk + header together via Ollama `qwen3-embedding:0.6b` into a `VECTOR(1024)` column.
- Upsert to `document_chunks`, storing `heading_path` and `content_type` inside the chunk's metadata.

**File Folder Structure** (under `temp/`):
- `pending-digest-docs/` — drop `.md` files here; `POST /ingest/file` reads from here.
- `processed/` — files moved here after successful ingestion.
- `failed/` — files moved here after 3 retries exhausted.

### 3. Memory System Workflow

**Fact Lifecycle:**
- User message contains a self-referential fact → Memory Agent extracts it under case `FACT_EXTRACTION`.
- `MemoryPersistenceNode` runs a cosine similarity check against existing `learned_facts` (threshold 0.85).
  - No conflict → embed fact via Ollama, upsert to `learned_facts`.
  - Conflict detected → populate `ConflictContext` (fields: `existing`, `existing_id`, `new`), set `awaiting_conflict_clarification=True`.
- Conflict is surfaced in the response, asking the user to clarify.
- On the next turn, Memory Agent runs case `CONFLICT_RESOLUTION`: deletes the conflicting IDs and writes the resolved fact.

**Correction Lifecycle:**
- Triggered when Synthesis produces `confidence < 0.7`: sets `is_uncertain=True` and `awaiting_correction=True`, persisted via LangGraph checkpointing.
- Response surfaces the uncertainty to the user.
- On the next user message:
  - If it is a correction → Memory Agent case `CORRECTION`: walks `messages` by type to extract `original_answer` + `correction` + `root_cause`.
  - If it is an unrelated query → Memory Agent resets `awaiting_correction=False` and performs normal `FACT_EXTRACTION`.
- For the correction path: `MemoryPersistenceNode` upserts to `model_corrections`, embeds the `correction` field specifically (not `original_answer`), and resets `awaiting_correction=False`.
