# Implementation Plan

The Second Brain build is sequenced as six independently testable tickets forming a dependency graph — Infrastructure → OTEL → (Ingestion ‖ Query Graph) → (Memory ‖ Evaluation) — with observability wired in before any feature ticket.

## Key Concepts

- Dated 2026-06-16; links to the PRD (`docs/002-project-requirement-document.md`) and the Design Spec (`docs/superpowers/specs/2026-06-16-second-brain-design.md`).
- Dependency graph across 6 tickets: Ticket 1 (Infrastructure) → Ticket 2 (OTEL + Phoenix) → Ticket 3 (Ingestion Pipeline) and Ticket 4 (Query Graph + PII) in parallel → Ticket 5 (Memory System, depends on both 3 and 4) and Ticket 6 (Evaluation Harness, depends on both 3 and 4).
- Each ticket produces independently testable, working software.
- OTEL is implemented before ingestion (Ticket 2 before Ticket 3/4) so every agent and endpoint is observable from day one.
- This plan sits between the PRD and the workflow/behavioral design in the requirements-to-implementation chain: raw ask → PRD → this ticket breakdown → Mermaid workflow design.

## Ticket Breakdown

- **Ticket 1 — Infrastructure & Project Foundation.** Plan doc: `docs/superpowers/plans/2026-06-16-ticket-1-infrastructure.md`. Goal: Docker services running, all 5 DB tables created, `GET /health` returns 200, Alembic migrations run cleanly. 6 tasks (~40 steps). Deliverables: `docker-compose.yml` (app_postgres, phoenix_postgres, phoenix, backend), all SQLModel models (`ChatHistory`, `IngestedDocument`, `DocumentChunk`, `LearnedFact`, `ModelCorrection`), Alembic initial migration, FastAPI skeleton. `DocumentChunk.metadata` is `chunk_metadata` in Python (SQL column stays `metadata`) to avoid a SQLAlchemy name conflict.
- **Ticket 2 — OTEL + Arize Phoenix.** Plan doc: `docs/superpowers/plans/2026-06-16-ticket-2-otel-phoenix.md`. Purpose: instrument the app before building features so every subsequent endpoint and LangGraph node is traceable from day one. Goal: a single `GET /health` request produces a visible end-to-end trace in the Phoenix UI at `http://localhost:6006`. 5 tasks. Deliverables: `observability/tracing.py` with `setup_tracing()` + `@trace_node` decorator, FastAPI auto-instrumentation, `extra_hosts` setting for Linux Docker compatibility. Backend reaches Phoenix via gRPC host port 4317 only — the networks remain isolated.
- **Ticket 3 — Document Ingestion Pipeline.** Plan doc: `docs/superpowers/plans/2026-06-16-ticket-3-ingestion.md`. Purpose: build the full ingestion flow from raw markdown to searchable pgvector chunks. Goal: dropping a `.md` file into `temp/pending-digest-docs/` and calling `POST /ingest/file` stores embedded chunks in pgvector; the file then moves to `temp/processed/`. 10 tasks. Deliverables: `services/chunking.py` (hybrid strategy), `services/embeddings.py` (Ollama `qwen3-embedding:0.6b`), `services/tavily.py`, `IngestionState` + LangGraph ingestion graph with `in_progress`/`retry_queue`, `POST /ingest/file` + `POST /ingest/url` endpoints. 3 retry attempts per file; code fences are protected via placeholder substitution before any text splitting.
- **Ticket 4 — Query Graph + PII Guardrail.** Plan doc: `docs/superpowers/plans/2026-06-16-ticket-4-query-graph.md`. Purpose: build the core `/query` flow with all retrieval agents, PII protection on both edges, and session continuity. Goal: `POST /query` returns a grounded answer, PII is redacted both inbound and outbound, and sessions continue across calls via UUID7 thread IDs. 12 tasks. Deliverables: `services/pii.py` (Presidio, broad-scope), `PIIRedactionNode` (inbound + outbound), `Orchestrator` (LLM-based routing), `RAGRetrievalNode`, `WebResearchNode` (Tavily), `SynthesisNode` (confidence scoring), `SecondBrainState`, LangGraph query graph using `Send` fan-out + `AsyncPostgresSaver` checkpointing. `MemoryRetrievalNode` is only a stub (returns an empty list) in this ticket — fully wired in Ticket 5.
- **Ticket 5 — Memory System.** Plan doc: `docs/superpowers/plans/2026-06-16-ticket-5-memory.md`. Purpose: add persistent cross-session memory — auto fact extraction, conflict detection, and model correction learning. Goal: AC-1 through AC-4 all pass — facts persist with embeddings, conflicts surface to the user, and the `awaiting_correction` state machine works correctly across turns. 8 tasks. Deliverables: `MemoryRetrievalNode` (full implementation, replacing the Ticket 4 stub), `MemoryAgentNode` (handles 3 cases: fact extraction, correction detection, conflict resolution), `MemoryPersistenceNode` (DB writes + embeddings), updated query graph. `ModelCorrection.embedding` encodes the `correction` field, not `original_answer`, so cosine-similarity retrieval surfaces the correct answer rather than the original mistake.
- **Ticket 6 — Evaluation Harness.** Plan doc: `docs/superpowers/plans/2026-06-16-ticket-6-evaluation.md`. Purpose: build offline eval tooling to prove RAG improves over a no-RAG baseline. Goal: `python eval/run_eval.py` produces a report showing RAGAS `context_recall` and `answer_faithfulness` are measurably higher for RAG than for the no-RAG baseline (AC-9). 7 tasks. Deliverables: `eval/generate_dataset.py` (Claude generates ~100 Q&A pairs), `eval/baseline.py` (direct Claude call, no retrieval), `eval/run_eval.py` (full RAGAS suite), `eval/compare.py` (markdown report with a delta column). Run offline on demand — not part of CI; the user manually curates the generated Q&A pairs down to ~30–50 before running the eval.

## Acceptance Criteria Coverage

- AC-1: Extracted facts persisted with embedding — Ticket 5.
- AC-2: Conflict detected → notification + flag — Ticket 5.
- AC-3: `awaiting_correction` resets on non-correction — Ticket 5.
- AC-4: Corrections persisted with root cause + embedding — Ticket 5.
- AC-5: User message PII redacted before reaching the LLM — Ticket 4.
- AC-6: `final_answer` PII redacted before being stored in chat history — Ticket 4.
- AC-7: File retried 3× then moved to `temp/failed/` — Ticket 3.
- AC-8: Duplicate file (matching hash) skipped — Ticket 3.
- AC-9: RAG RAGAS metrics exceed the no-RAG baseline — Ticket 6.
- AC-10: `sessionId=null` creates a new thread; a UUID7 session id continues an existing thread — Ticket 4.

## Sources

- Implementation Plan — Second Brain — `docs/business/003-implementation.md`
- Business Index — `docs/business/000-index.md`

## Related Topics

- [[infrastructure-setup]]
- [[otel-phoenix-tracing]]
- [[document-ingestion-pipeline]]
- [[query-graph]]
- [[memory-system]]
- [[evaluation-harness]]
- [[project-requirements]]
- [[autonomous-feature-development-loop]]
- [[query-workflow]]
