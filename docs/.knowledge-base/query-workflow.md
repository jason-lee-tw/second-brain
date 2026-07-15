# Query Workflow

The `POST /query` request flows through a fixed 9-step sequence on the `SecondBrainState` LangGraph graph — PII redaction, memory retrieval, orchestrated fan-out to RAG/web, synthesis, outbound redaction, and memory persistence — before returning an answer with confidence and session continuity.

## Key Concepts

- **Trigger**: `POST /query` with `message` + `sessionId`. `sessionId` is the LangGraph `threadId`: `null` starts a new thread; a returning UUID7 continues the same thread via `AsyncPostgresSaver` checkpointing.
- **Step B — `PIIRedactionNode` (inbound, rule-based)**: redacts `messages[-1].content` before any LLM sees it, replacing PII with typed placeholders — NAME, EMAIL, PHONE, ADDRESS, ID, CARD, MEDICAL.
- **Step C — `MemoryRetrievalNode` (tool call)**: cosine similarity search over `learned_facts` + `model_corrections`, populates `retrieved_memory`.
- **Step D — `Orchestrator` (model `claude-haiku-4-5`)**: reads `messages[-1]` + `retrieved_memory`, routes via LangGraph `Send` fan-out to one or more of: `rag`, `web`, `both`, `neither`.
- **Step E — `RAG Retrieval` (tool call)**: embeds the query via Ollama, pgvector cosine similarity top-k=5 over `document_chunks`.
- **Step F — `Web Research` (model `claude-haiku-4-5`)**: Tavily search, top-3 results.
- **Step G — pass-through path**: when the Orchestrator routes to `neither`, the graph uses chat history + memory only, with no RAG/web lookups.
- **Step H — `Synthesis` (model `claude-sonnet-4-6`)**: combines `rag_results` + `web_results` + `retrieved_memory` + `messages` to produce `final_answer` + `confidence` (0–1 scale).
  - If `confidence < 0.7`: sets `is_uncertain=True` and `awaiting_correction=True`.
  - If `confidence >= 0.7`: sets `is_uncertain=False`.
- **Step I — `PIIRedactionNode` (outbound, rule-based)**: redacts `final_answer` before it's appended to `messages` / chat history.
- **Step J — `Memory Agent` (model `claude-haiku-4-5`)**: uses `with_structured_output(MemoryAgentOutput)`, classifies the turn via `MemoryCase` into one of four branches: `FACT_EXTRACTION` (default), `CORRECTION` (when `awaiting_correction=True`, either extracting a real correction or falling back to fact extraction if the next message is unrelated), or `CONFLICT_RESOLUTION` (when `awaiting_conflict_clarification=True`). See [[memory-system]] for the full lifecycle this step feeds into.
- **Step K — `MemoryPersistenceNode` (tool call)**: writes `fact_updates` → `learned_facts`, `correction_updates` → `model_corrections`, generating embeddings via Ollama and retrying each write up to 3 times. A cosine similarity conflict (> 0.85 against existing facts) sets `awaiting_conflict_clarification=True` and populates a `ConflictContext` surfaced in the response; otherwise it passes through.
- **Final response (N)**: returns `answer` + `sessionId` + `confidence` + `isUncertain` + `conflictDetected` + `conflictContext`.

## Agent Responsibility Table

| Node | Model | Role |
|---|---|---|
| PIIRedactionNode (in) | rule-based | Redact PII from `messages[-1]` before any LLM sees it |
| MemoryRetrievalNode | tool call | Cosine similarity on `learned_facts` + `model_corrections`, populates `retrieved_memory` |
| Orchestrator | `claude-haiku-4-5` | Routes to rag/web/both/neither via LangGraph `Send` fan-out |
| RAG Retrieval | tool call | Embed query via Ollama, pgvector top-k=5 from `document_chunks` |
| Web Research | `claude-haiku-4-5` | Tavily search, top-3 results |
| Synthesis | `claude-sonnet-4-6` | Produces `final_answer` + `confidence`; sets uncertainty flags when `confidence < 0.7` |
| PIIRedactionNode (out) | rule-based | Redact `final_answer` before persisting to chat history |
| Memory Agent | `claude-haiku-4-5` | Classifies turn as FACT_EXTRACTION / CORRECTION / CONFLICT_RESOLUTION, outputs structured `MemoryAgentOutput` |
| MemoryPersistenceNode | tool call | Writes facts + corrections with embeddings; conflict-checks via cosine similarity (threshold 0.85) |

## State Flag Invariants

- `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive.
- Entering `CONFLICT_RESOLUTION` always resets `awaiting_correction=False`.
- Session continuity: `sessionId` is the LangGraph `threadId` — `null` starts a new thread, a returning UUID7 continues the same thread via `AsyncPostgresSaver` checkpointing.

## Open Questions

- **memory_conflict_threshold default**: this page implies `0.85` (cosine similarity conflict threshold), but [[integration-testing]] and [[pgvector-embeddings]] describe the same conflict-check code path with the value bound as `0.95`. Unresolved — needs source verification.
- **MemoryCase branch count**: this page says `MemoryCase` has four branches but only lists three; [[memory-system]] and [[second-brain-architecture]] say three. Unresolved.

## Sources

- Business Index — `docs/business/000-index.md`
- Workflow Design — `docs/business/004-workflow-design.md`

## Related Topics

- [[query-graph]]
- [[memory-system]]
- [[document-ingestion-pipeline]]
- [[second-brain-architecture]]
- [[multi-agent-architecture]]
- [[implementation-plan]]
- [[pgvector-embeddings]]
- [[project-requirements]]
- [[evaluation-harness]]
