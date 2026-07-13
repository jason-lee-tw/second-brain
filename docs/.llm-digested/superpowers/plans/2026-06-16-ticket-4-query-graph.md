# Ticket 4: Query Graph Implementation Plan

Source: docs/superpowers/plans/2026-06-16-ticket-4-query-graph.md
Primary-Topic: query-graph
Secondary-Topics: pii-redaction, session-continuity

## Key Concepts

- **Goal**: build the full `POST /query` flow — PII guardrail (inbound + outbound), LLM orchestrator routing, RAG retrieval, web research, synthesis with confidence scoring, and session continuity via LangGraph checkpointing with `PostgresSaver`.
- **Architecture**: a `StateGraph(SecondBrainState)` wires eight nodes sequentially with a fan-out step: `redact_inbound → retrieve_memory → orchestrator → (Send fan-out) → rag_retrieval / web_research → synthesis → redact_outbound`. The graph is checkpointed per `thread_id` (= `session_id`) in Postgres so conversation history persists across API calls.
- `messages` field uses LangGraph's `add_messages` reducer so new messages are appended to the checkpoint rather than overwriting it.
- **Tech stack for this ticket**: FastAPI, LangGraph (`StateGraph`, `Send`, `AsyncPostgresSaver`), `langchain-anthropic` (`claude-haiku-4-5` for routing, `claude-sonnet-4-6` for synthesis), `presidio-analyzer` + `presidio-anonymizer` + spaCy `en_core_web_lg` (PII), `pgvector-python` + `asyncpg` (RAG), Ollama `qwen3-embedding:0.6b` (embeddings), Tavily Python SDK (web search), `uuid6` (session IDs, `uuid7()`), `psycopg-pool` (Postgres checkpointer pool), `pytest-asyncio`.

### File map (created/modified)
- `graphs/state.py` — `SecondBrainState` + supporting TypedDicts (modify; keep existing `IngestionState`)
- `services/pii.py` — `redact_pii(text) -> str` using Presidio
- `nodes/pii_redaction.py` — inbound + outbound PII graph nodes
- `nodes/memory_retrieval.py` — stub returning `retrieved_memory=[]` (full impl deferred to Ticket 5)
- `nodes/orchestrator.py` — LLM routing via `claude-haiku-4-5`
- `nodes/rag_retrieval.py` — pgvector cosine similarity, top-k=5
- `nodes/web_research.py` — Tavily search, rate-limited to 1 req/sec
- `nodes/synthesis.py` — `claude-sonnet-4-6`, confidence scoring
- `graphs/query_graph.py` — full LangGraph with `PostgresSaver`
- `api/schemas.py` — adds `QueryRequest`, `QueryResponse` (modify; keep existing ingestion schemas)
- `api/routers/query.py` — `POST /query` handler
- `main.py` — registers `/query` router (modify)
- `tests/unit/conftest.py` — `make_state()` factory for all unit tests
- corresponding unit tests per node/service, plus `tests/integration/test_query_graph.py` covering AC-5, AC-6, AC-10

### SecondBrainState (graphs/state.py)
- TypedDicts: `RagResult` (`content`, `score`, `chunk_index`, `metadata`), `WebResult` (`title`, `url`, `content`), `MemoryItem` (`id`, `fact`, `confidence`, `type: Literal["learned_fact","model_correction"]`), `FactUpdate` (`fact`, `confidence`, `conflicts_with: list[str]`), `CorrectionUpdate` (`original_answer`, `correction`, `root_cause` — populated from `messages[-2]`).
- `SecondBrainState` fields: `session_id`, `messages: Annotated[list[BaseMessage], add_messages]`, `rag_results`, `web_results`, `retrieved_memory`, `routing_decision: Literal["rag","web","both","neither"]`, `final_answer`, `confidence`, `is_uncertain`, `awaiting_correction` (persisted across turns via checkpointing), `awaiting_conflict_clarification`, `conflict_context`, `fact_updates` (Ticket 5), `correction_updates` (Ticket 5).
- `make_state(**overrides)` test factory in `tests/unit/conftest.py` provides safe defaults for all fields (used across all node unit tests).

### PII redaction (services/pii.py, nodes/pii_redaction.py)
- `redact_pii(text)` uses Presidio `AnalyzerEngine` + `AnonymizerEngine` (module-level singletons — spaCy load is expensive, done once).
- Entities detected: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `DATE_TIME`, `CREDIT_CARD`, `IBAN_CODE`, `MEDICAL_LICENSE`, `NRP`, `US_SSN`, `US_PASSPORT`, `IP_ADDRESS`.
- Replacement placeholders: `[NAME]`, `[EMAIL]`, `[PHONE]`, `[ADDRESS]` (LOCATION), `[DATE]`, `[CARD]` (CREDIT_CARD + IBAN_CODE), `[MEDICAL]`, `[ID]` (NRP/SSN/passport), `[IP]`.
- Empty string / no detections pass through unchanged.
- `redact_inbound(state)`: redacts only `messages[-1].content`, preserves the message `id` so LangGraph's `add_messages` reducer replaces in place rather than appending a duplicate; returns `{"messages": [redacted_message]}` (only the last message, not full history — earlier messages persist in the checkpoint untouched).
- `redact_outbound(state)`: redacts `state["final_answer"]`, returns `{"final_answer": redact_pii(...)}`.
- This implements AC-5 (inbound PII stripped before any LLM node sees it) and AC-6 (outbound PII stripped before persistence/return).

### Memory retrieval stub (nodes/memory_retrieval.py)
- `retrieve_memory(state)` is an async stub always returning `{"retrieved_memory": []}` for Ticket 4.
- Full implementation (pgvector cosine similarity search across `learned_facts` and `model_corrections` tables) is deferred to Ticket 5; the stub exists so Ticket 5 can drop in the real implementation without graph rewiring.

### Orchestrator / routing (nodes/orchestrator.py)
- `route_query(state)` calls a structured-output LLM (`_structured_llm = ChatAnthropic(model="claude-haiku-4-5").with_structured_output(_RoutingOutput)`) with a prompt containing the memory context (joined `retrieved_memory` facts, or "No memory context available.") and the current query (`messages[-1].content`).
- `_RoutingOutput` Pydantic model: `routing_decision: Literal["rag","web","both","neither"]`, `reasoning: str`.
- Routing semantics: `"rag"` = personal notes/docs; `"web"` = current/real-time info; `"both"` = benefits from both; `"neither"` = purely conversational.
- Returns `{"routing_decision": result.routing_decision}`.

### RAG retrieval (nodes/rag_retrieval.py)
- `_embed_query(query, base_url)`: POSTs to Ollama `{base_url}/api/embeddings` with `model="qwen3-embedding:0.6b"`, returns the embedding vector (dim 1024 in tests).
- `_query_pgvector(embedding, postgres_url, top_k=5)`: opens an `asyncpg` connection, calls `register_vector(conn)` (pgvector-asyncpg), runs a cosine-similarity query (`1 - (embedding <=> $1) AS score`, `ORDER BY embedding <=> $1 LIMIT $2`) against `document_chunks`, closes the connection in a `finally` block.
- `retrieve_from_rag(state)`: embeds `messages[-1].content` via `settings.ollama_base_url`, queries pgvector via `settings.app_postgres_url`, maps rows into `RagResult` items, returns `{"rag_results": [...]}` (empty list when no rows).
- Depends on `settings.app_postgres_url` and `settings.ollama_base_url` existing in `core/config.py` (from Ticket 1).

### Web research (nodes/web_research.py)
- `search_web(state)`: rate-limited via `await asyncio.sleep(1)` before every Tavily call (max 1 request/sec) — called unconditionally at the top of the function, verified by `mock_sleep.assert_called_once_with(1)`.
- Uses `TavilyClient(api_key=settings.tavily_api_key)`; since the Tavily SDK is synchronous, the actual `client.search(query, max_results=3)` call is offloaded to the default executor via `loop.run_in_executor` to avoid blocking the event loop.
- Query is `messages[-1].content`; maps Tavily's `results` (each with `title`, `url`, `content`) into `WebResult` items; returns `{"web_results": [...]}` (empty list when no results).

### Synthesis (nodes/synthesis.py)
- `synthesize_answer(state)` calls `_structured_llm = ChatAnthropic(model="claude-sonnet-4-6").with_structured_output(_SynthesisOutput)`.
- `_SynthesisOutput`: `final_answer: str`, `confidence: float` (0.0–1.0, via `Field(ge=0.0, le=1.0)`), `reasoning: str`.
- Prompt combines: `rag_results` (formatted with score), `web_results` (title/url/content), `retrieved_memory` (facts), and conversation history trimmed to the **last 10 messages excluding the current query** (`state["messages"][-10:-1]`), plus the current query.
- `_UNCERTAINTY_THRESHOLD = 0.7`: `is_uncertain = confidence < 0.7`.
- `_NEITHER_CONFIDENCE_FLOOR = 0.5`: when `routing_decision == "neither"`, `confidence = max(llm_confidence, 0.5)` — i.e. floors confidence upward for purely conversational turns, never lowers a higher LLM-reported confidence.
- Returns `{"final_answer": ..., "confidence": ..., "is_uncertain": ...}`.

### Query graph wiring (graphs/query_graph.py)
- `build_query_graph(postgres_url)`: opens an `AsyncConnectionPool(conninfo=postgres_url, open=False)` then `await pool.open()`; creates `AsyncPostgresSaver(pool)` and calls `await checkpointer.setup()` (creates LangGraph checkpoint tables if absent).
- Builds `StateGraph(SecondBrainState)`, registers nodes: `redact_inbound`, `retrieve_memory`, `orchestrator`, `rag_retrieval`, `web_research`, `synthesis`, `redact_outbound`.
- Linear edges: entry point `redact_inbound` → `retrieve_memory` → `orchestrator`.
- Conditional fan-out from `orchestrator` via `_route_retrieval(state)`:
  - `"both"` → `[Send("rag_retrieval", state), Send("web_research", state)]` (parallel)
  - `"rag"` → `[Send("rag_retrieval", state)]`
  - `"web"` → `[Send("web_research", state)]`
  - `"neither"` → routes directly to the string `"synthesis"`, skipping retrieval entirely
- Both `rag_retrieval` and `web_research` converge on `synthesis`; `synthesis` → `redact_outbound` → `END`.
- `workflow.compile(checkpointer=checkpointer)` — the compiled graph is intended to be built once at app startup and is thread-safe for concurrent use across sessions (each session is a distinct `thread_id`).

### API schemas and router (api/schemas.py, api/routers/query.py, main.py)
- `QueryRequest`: `message: str`, `sessionId: Optional[str] = None` (UUID7 or null for new session).
- `QueryResponse`: `answer: str`, `sessionId: str` (UUID7 to reuse for continuation), `confidence: float`, `isUncertain: bool`, `conflictDetected: bool`, `conflictContext: list[str]`.
- `api/routers/query.py` defines `router = APIRouter(prefix="/query", tags=["query"])` with a module-level lazily-initialized compiled graph singleton (`_graph`, built via `_get_graph()` calling `build_query_graph(settings.app_postgres_url)` on first use).
- `POST /query` handler: `session_id = request.sessionId or str(uuid7())`; builds the full initial `SecondBrainState` dict (all fields defaulted, `messages=[HumanMessage(content=request.message)]`); invokes `graph.ainvoke(input_state, config={"configurable": {"thread_id": session_id}})`; wraps invocation errors as `HTTPException(500, ...)`; maps `result` fields into `QueryResponse`, with `conflictDetected = bool(conflict_context)`.
- `main.py` gains `from second_brain.api.routers.query import router as query_router` and `app.include_router(query_router)`.

### Testing approach and acceptance criteria
- Each node/service ships with TDD-style failing-test-first unit tests using `unittest.mock.patch` on the module-level `_structured_llm` / `TavilyClient` / `_embed_query` / `_query_pgvector` singletons, and the shared `make_state()` factory.
- Notable test behaviors: `redact_inbound` preserves message `id` so only the last message is replaced, not duplicated; orchestrator/synthesis tests assert the exact prompt text contains memory context or trimmed history; web research asserts rate-limit sleep and executor offload; RAG retrieval asserts `_embed_query`/`_query_pgvector` are called with the right args and mapped fields.
- Integration tests (`tests/integration/test_query_graph.py`, marked `@pytest.mark.integration`) build the **real** graph against a running Postgres (`docker compose up -d app_postgres`) but mock all LLM/Tavily calls, covering three acceptance criteria explicitly:
  - **AC-5**: PII in the inbound message must not appear in what the orchestrator LLM receives (asserted via a capturing mock on `orchestrator._structured_llm.ainvoke`).
  - **AC-6**: PII appearing in the LLM-synthesized `final_answer` must be absent from the graph's returned `final_answer` (redacted by `redact_outbound` before the graph ends).
  - **AC-10**: calling `query_endpoint` with `sessionId=None` creates a new thread and returns a UUID7; a second call using that returned `sessionId` continues the same thread (checkpoint accumulates messages via `add_messages`), verified by asserting the second synthesis call is distinguishable as "turn 2".
- Full "Done Checklist" for Ticket 4: `POST /query` with null `sessionId` returns a UUID7 + grounded answer; reusing that UUID7 continues the same conversation; PII in inbound messages redacted before any LLM node (AC-5); PII in `final_answer` redacted before return/persistence (AC-6); confidence < 0.7 sets `isUncertain: true`; `routing_decision == "neither"` applies a 0.5 confidence floor; all unit tests pass; all integration tests pass against a running Postgres.
- Recommended sub-skill for implementing this plan task-by-task: `superpowers:subagent-driven-development` (or `superpowers:executing-plans`), using the plan's `- [ ]` checkbox steps for tracking.
