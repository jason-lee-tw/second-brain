# Query Graph

The `SecondBrainState` LangGraph graph powering `POST /query` — PII redaction, memory retrieval, LLM-driven routing, parallel RAG/web retrieval, confidence-scored synthesis, and Postgres-backed session continuity.

## Key Concepts

- **Purpose and contract**: serves `POST /query` — request `{ "message": string, "sessionId": UUID7 | null }`; response `{ "answer": string, "sessionId": UUID7, "confidence": float, "isUncertain": bool, "conflictDetected": bool, "conflictContext": [] }`. `sessionId=null` starts a new conversation; a returned UUID7 continues an existing one — it is both the LangGraph `thread_id` and the chat-history key. `isUncertain=true` when `confidence < 0.7`; `conflictDetected=true` when a newly extracted fact conflicts with existing memory.
- **Graph shape**: `StateGraph(SecondBrainState)` with entry point `redact_inbound → memory_retrieval_node → orchestrator`, then a conditional fan-out from `orchestrator` via `_route_retrieval(state)`: `"both"` → parallel `Send("rag_retrieval", state)` + `Send("web_research", state)`; `"rag"` → only RAG; `"web"` → only web research; `"neither"` → routes straight to `"synthesis"`, skipping retrieval. Both retrieval branches converge on `synthesis → redact_outbound`. In the original Ticket 4 build the tail ended at `redact_outbound → END`; the Ticket 5 memory work rewired the tail to `redact_outbound → memory_agent → memory_persistence → END` so every turn also runs fact/correction extraction and persistence before finishing (see [[memory-system]] for that node's internals).
- **Two independent graphs**: `SecondBrainState` (this page, query-side) and `IngestionState` (see [[document-ingestion-pipeline]]) share the same database but no runtime state — kept as separate LangGraph state schemas deliberately, to keep each schema clean.
- **`messages` reducer**: `Annotated[list[BaseMessage], add_messages]` — new messages are appended to the checkpoint rather than overwriting it, which is what lets PII redaction replace a single message in place (see below) without duplicating it.
- **`SecondBrainState` fields**: `session_id`, `messages`, `rag_results`, `web_results`, `retrieved_memory`, `routing_decision: Literal["rag","web","both","neither"]`, `final_answer`, `confidence`, `is_uncertain`, `awaiting_correction` (persisted across turns via checkpointing), `awaiting_conflict_clarification`, `conflict_context` (`list[ConflictContext]` as of the memory-system work — was `list[str]`), `fact_updates`, `correction_updates`. Supporting TypedDicts: `RagResult` (content, score, chunk_index, metadata), `WebResult` (title, url, content), `MemoryItem` (id, fact, confidence, type).
- **PII redaction nodes** (`services/pii.py`, `nodes/pii_redaction.py`): Presidio `AnalyzerEngine` + `AnonymizerEngine` module-level singletons detect `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `DATE_TIME`, `CREDIT_CARD`, `IBAN_CODE`, `MEDICAL_LICENSE`, `NRP`, `US_SSN`, `US_PASSPORT`, `IP_ADDRESS`, replaced with typed placeholders (`[NAME]`, `[EMAIL]`, `[PHONE]`, `[ADDRESS]`, `[DATE]`, `[CARD]`, `[MEDICAL]`, `[ID]`, `[IP]`). `redact_inbound` redacts only `messages[-1].content` and preserves the message `id` so the `add_messages` reducer replaces it in place instead of appending a duplicate — this satisfies AC-5 (inbound PII stripped before any LLM node sees it). `redact_outbound` redacts `final_answer` before it is appended to `messages`/persisted — AC-6.
- **Memory retrieval node**: shipped in Ticket 4 as an async stub (`retrieve_memory`, always `{"retrieved_memory": []}`) explicitly so Ticket 5 could drop in the real implementation without rewiring the graph. Ticket 5 replaced it with `memory_retrieval_node` — same node position (`redact_inbound → memory_retrieval_node → orchestrator`), same function/node-name convention — running real pgvector cosine-similarity search over `learned_facts` and `model_corrections`. Full behavior documented in [[memory-system]].
- **Orchestrator / routing**: `route_query(state)` calls `ChatAnthropic(model_name="claude-haiku-4-5").with_structured_output(_RoutingOutput)` with the joined memory context and the current query, returning `routing_decision: Literal["rag","web","both","neither"]`. This is the "Single Supervisor Graph" multi-agent pattern (see [[multi-agent-architecture]]): the orchestrator is an LLM-powered node, not rule-based, and is what drives the `Send`-based fan-out — a hierarchical multi-graph and an agent-as-tool/ReAct pattern were both considered and rejected as added indirection or harder to guarantee fan-out and a synthesis step at this project's scope.
- **RAG retrieval** (`nodes/rag_retrieval.py`): embeds `messages[-1].content` via Ollama, queries pgvector top-k=5 via `asyncpg` (cosine similarity `1 - (embedding <=> $1)`), returns `RagResult` items. See [[pgvector-embeddings]] and [[postgres-connection-pooling]] for the shared asyncpg pool this node uses.
- **Web research** (`nodes/web_research.py`): rate-limited to 1 request/sec (`asyncio.sleep(1)` before every call), runs the synchronous Tavily `client.search(query, max_results=3)` via `loop.run_in_executor` to avoid blocking the event loop, maps results into `WebResult` items.
- **Synthesis** (`nodes/synthesis.py`): `ChatAnthropic(model_name="claude-sonnet-4-6").with_structured_output(_SynthesisOutput)` combines RAG results, web results, retrieved memory, and the last 10 messages of history (excluding the current query) into a final answer + confidence. `_UNCERTAINTY_THRESHOLD = 0.7` sets `is_uncertain`; `_NEITHER_CONFIDENCE_FLOOR = 0.5` floors confidence upward (never down) when `routing_decision == "neither"`. As of the memory-system work, synthesis also sets `awaiting_correction = is_uncertain` in the same return, since it's the node that already holds `confidence` in scope.
- **Session continuity / checkpointing**: `build_query_graph(postgres_url)` opens a `psycopg_pool.AsyncConnectionPool(conninfo=postgres_url, open=False)`, calls `await pool.open()`, constructs `AsyncPostgresSaver(pool)`, and calls `await checkpointer.setup()` to create the LangGraph checkpoint tables. The compiled graph (`workflow.compile(checkpointer=checkpointer)`) is built once at app startup and is thread-safe for concurrent use across sessions, each keyed by a distinct `thread_id` (= `session_id`). This `AsyncConnectionPool` (psycopg3 driver) is separate from the `asyncpg.Pool` singleton used by RAG/memory retrieval — the two drivers cannot share a pool. `POST /query` uses `session_id = request.sessionId or str(uuid7())` and invokes `graph.ainvoke(state, config={"configurable": {"thread_id": session_id}})` — AC-10 coverage.
- **API surface**: `api/routers/query.py` (`POST /query`, prefix `/query`), lazily builds the compiled graph singleton on first request; `api/schemas.py` adds `QueryRequest`/`QueryResponse`; `main.py` registers the router.

## Type Safety on This Graph

A later type-check remediation pass (see [[type-checking]]) touched every node in this graph without changing behavior: each node's bare `dict` return was replaced with a dedicated `TypedDict` (`RedactInboundOutput`, `RedactOutboundOutput`, `RetrieveMemoryOutput`, `RouteQueryOutput`, `RagRetrievalOutput`, `WebResearchOutput`, `SynthesisNodeOutput`), `ChatAnthropic(model=...)` calls in the orchestrator and synthesis nodes were changed to `model_name=...` (the stub only types that kwarg), and `build_query_graph`'s return type was made explicit as `tuple[CompiledStateGraph[SecondBrainState, None, SecondBrainState, SecondBrainState], AsyncConnectionPool[Any]]` — the `Any` on the pool's row-factory type parameter is an approved exception to the project's no-`Any` rule since it is imposed by the psycopg stub, not project code. `AsyncPostgresSaver(pool)` also needed a targeted `# type: ignore[arg-type]` for a LangGraph checkpointer stub gap (psycopg pool type vs. LangGraph's `Conn` stub).

## Sources

- Task 001 — Fix Type-Check Errors — `docs/bugs/001-fix-typecheck-error.md`
- Project Requirement Document — Second Brain — `docs/business/002-project-requirement-document.md`
- Document Ingestion Pipeline — Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-3-ingestion.md`
- Ticket 4: Query Graph Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-4-query-graph.md`
- Memory System Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-5-memory.md`
- Fix Type-Check Errors Implementation Plan — `docs/superpowers/plans/2026-06-24-fix-typecheck-errors.md`
- Fix AsyncConnectionPool autocommit for LangGraph checkpointer — `docs/superpowers/specs/2026-06-24-query-graph-autocommit-fix.md`

## Related Topics

- [[query-graph-autocommit-fix]]
- [[memory-system]]
- [[document-ingestion-pipeline]]
- [[type-checking]]
- [[second-brain-requirements]]
- [[multi-agent-architecture]]
- [[pgvector-embeddings]]
- [[postgres-connection-pooling]]
- [[database-access-patterns]]
- [[implementation-plan]]
- [[integration-testing]]
- [[query-workflow]]
- [[second-brain-architecture]]
- [[system-architecture]]
