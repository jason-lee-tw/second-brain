# Node Base-Class Refactor Implementation Plan

Source: docs/superpowers/plans/2026-07-07-node-base-class-refactor.md
Primary-Topic: node-base-class-refactor
Secondary-Topics: query-graph, document-ingestion-pipeline

## Key Concepts

- Goal: convert every LangGraph node under `apps/backend/src/second_brain/nodes/` to extend `BaseNode` or `BaseAgentNode`, with each agent-based node owning its own `ClaudeAgent` internally so graph files never construct or name a model directly.
- Architecture is an in-place conversion: every node module keeps its file path and its current public symbol name, rebound from a bare function to a `__call__`-able class instance — graph files therefore need zero or near-zero edits (they call `add_node("name", instance)` exactly as before, since instances are callables).
- Helpers that don't touch `self` remain module-level private functions; only helpers that touch `self._agent`/a cached model become instance methods. This is an explicit "method rule" applied consistently across all 11 node conversions.
- Naming rule: the module's existing public symbol (the name graphs/tests import) is rebound from function to singleton instance — the name itself never changes, preserving import compatibility.
- Full design rationale lives in a companion spec: `docs/superpowers/specs/2026-07-07-node-base-class-refactor-design.md` (decisions 3 and 6-8 referenced for approved behavior exceptions).
- Tech stack touched: Python 3.13, LangGraph, LangChain (`langchain-anthropic`), Pydantic, SQLModel/asyncpg, pytest + pytest-asyncio, basedpyright, ruff.
- This is explicitly framed as a **behavior-preserving structural refactor** with exactly three/four approved exceptions:
  1. `orchestrator`/`memory_agent`/`synthesis` move from an unset (`None`, effectively ~1.0) temperature to `ClaudeAgent`'s default `temperature=0.7`.
  2. `ingestion_agent`'s header generation moves from the raw `anthropic.AsyncAnthropic` SDK client to `ClaudeAgent`/`ChatAnthropic`.
  3. `settings.ingestion_model` config field and `ingestion_agent.shutdown()` (plus its two call sites in `main.py`) are deleted as dead code.
  4. `orchestrator`/`memory_agent`/`ingestion_agent` move from the undated rolling alias `"claude-haiku-4-5"` to the dated snapshot `CLAUDE_MODEL_NAME.HAIKU = "claude-haiku-4-5-20251001"`, accepted for reproducibility since a rolling alias can silently change model behavior without a code change.
- Global constraints for every task: `just lint`, `just format`, `just type-check` clean and `just test-unit` fully green (project's "Done Means"); commits follow Conventional Commits (enforced by `.hooks/commit-msg`); no suppressing errors with broad excepts (except pre-existing broad-catch teardown paths in `main.py`, out of scope); no new dependencies.
- Per-task verification cycle for pure structural moves already covered by an existing passing test file: convert source → update test patch targets to match new structure → run the test file → confirm PASS. This is explicitly NOT a contrived red-green cycle because the correctness spec already lives in the existing test. Only Task 11's header-generation change (genuine behavior change) gets a real failing-test-first cycle.
- **Task 1 — Fix `BaseAgentNode`/`BaseNode` contract bugs, export `CLAUDE_MODEL_NAME`:**
  - Files: `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`, `base_node.py`, `agents/__init__.py`.
  - Bug found (verified live against the repo's basedpyright config): abstract `__call__` on both base classes was declared sync-only, so every planned `async def __call__` override (8 of 11 subclasses across later tasks) would fail `just type-check` with a hard `reportIncompatibleMethodOverride`; also every override lacking `@override` would fail `reportImplicitOverride` (a warning, but one that still fails `just type-check`'s exit code).
  - Fix: widen `__call__`'s return type on both `BaseNode` and `BaseAgentNode` to `Awaitable[ResultStateType] | ResultStateType`, and require `@override` on every concrete subclass. This keeps real override-safety checking active instead of suppressing it project-wide.
  - `BaseAgentNode[InputStateType, ResultStateType]` is a generic ABC holding `_agent: BaseAgent`, set via `__init__(self, agent: BaseAgent)`.
  - `BaseNode[InputStateType, ResultStateType]` is a generic ABC with a bare abstract `__call__`.
  - Export `CLAUDE_MODEL_NAME` alongside `ClaudeAgent`/`BaseAgent` from `second_brain.nodes.base_node.agents.__init__` so later tasks can `from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent`.
  - No new business logic/tests needed beyond the existing full suite since there are no existing `BaseNode`/`BaseAgentNode` subclasses yet — the change is invisible at runtime and at every current call site.
  - Verification: `just lint && just type-check && just test-unit`.
  - Commit message: "fix: correct BaseNode/BaseAgentNode __call__ contract (annotation + async-compatible return type), export CLAUDE_MODEL_NAME".
- **Task 2 — `pii_redaction.py` → `RedactInboundNode`/`RedactOutboundNode`:**
  - Both are sync `BaseNode` subclasses (no agent). `RedactInboundNode.__call__` redacts PII from the last message via `redact_pii` (from `second_brain.services.pii`), returning a replacement `HumanMessage` with the same id (relies on LangGraph's `add_messages` reducer replacing by id, preserving prior messages) — raises `ValueError` if `state["messages"]` is empty.
  - `RedactOutboundNode.__call__` redacts PII from `state["final_answer"]`.
  - Singletons: `redact_inbound = RedactInboundNode()`, `redact_outbound = RedactOutboundNode()` — same names, same sync call signature (no `await`) as before.
  - No test file changes needed; existing `test_pii_redaction.py` (6 tests) stays green because only the object type behind the names changed (function → instance).
  - Commit: "refactor: convert pii_redaction nodes to BaseNode subclasses".
- **Task 3 — `web_research.py` → `WebResearchNode`:**
  - Async `BaseNode` subclass. Uses `TavilyClient` (module-level import, so test patch targets unchanged) via `asyncio.to_thread` to call `.search(query, max_results=3)`, mapping results into `WebResult` dicts (title/url/content).
  - Singleton: `search_web = WebResearchNode()`.
  - Commit: "refactor: convert web_research node to BaseNode subclass".
- **Task 4 — `rag_retrieval.py` → `RagRetrievalNode`:**
  - Async `BaseNode` subclass. Keeps `_row_to_chunk_metadata`, `_embed_query`, `_query_pgvector` as module-level functions (no `self` dependency) — test patch targets unchanged.
  - `_embed_query` posts to a local Ollama embedding endpoint (`{base_url}/api/embeddings`, model `qwen3-embedding:0.6b`).
  - `_query_pgvector` runs a cosine-similarity SQL query (`embedding<=>$1`) against `document_chunks`, returning `RagResult` dicts with content/score/chunk_index/metadata, using `get_pgvector_pool()`.
  - Singleton: `retrieve_from_rag = RagRetrievalNode()`.
  - Commit: "refactor: convert rag_retrieval node to BaseNode subclass".
- **Task 5 — `memory_retrieval.py` → `MemoryRetrievalNode`:**
  - Async `BaseNode` subclass, "dual-table cosine search" — searches `learned_facts` and `model_corrections` tables in parallel via `asyncio.gather`, using `settings.memory_retrieval_threshold` to bound distance.
  - `_search_facts`/`_search_corrections` stay module-level functions (no `self`).
  - `__call__` fails hard on Ollama unavailability (no empty-list fallback) except when there's no last human message, in which case it returns `{"retrieved_memory": []}`.
  - Results are merged and sorted by score descending.
  - Singleton: `memory_retrieval_node = MemoryRetrievalNode()`.
  - Commit: "refactor: convert memory_retrieval node to BaseNode subclass".
- **Task 6 — `memory_persistence.py` → `MemoryPersistenceNode`:**
  - Async `BaseNode` subclass writing facts/corrections to the DB. Conflict-check reads use the asyncpg pool (`get_pgvector_pool`); writes use SQLModel sync `Session(engine)` wrapped in `asyncio.to_thread`; per-fact retry logic (`_retry_write`, up to `_MAX_RETRIES=3` attempts) before raising.
  - Contains the "F1 fix": `skip_conflict_check` prevents re-triggering `_conflict_check` when the LLM omits `conflicts_with` during a conflict-resolution turn, avoiding an infinite loop.
  - `_conflict_check`, `_retry_write`, `_write_fact`, `_write_correction`, `_persist_fact` all stay module-level (no `self` dependency).
  - `__call__` processes `fact_updates` and `correction_updates` from state, builds `conflict_contexts`/`pending_facts` when conflicts are found, sets `awaiting_correction`/`awaiting_conflict_clarification` flags for cross-turn state-machine transitions, and appends a conflict-clarification message to `final_answer` when conflicts exist.
  - Singleton: `memory_persistence_node = MemoryPersistenceNode()`.
  - Commit: "refactor: convert memory_persistence node to BaseNode subclass".
- **Task 7 — Create `nodes/pick_file.py`, update `ingestion_graph.py`:**
  - New module `PickFileNode` (sync `BaseNode` subclass) extracted out of the ingestion graph itself — moves the next pending or retry file into `in_progress`. Priority: `files[]` (first-timers) before `retry_queue`. Does NOT remove the item from `retry_queue` (that's `ingestion_agent_node`'s job, to preserve retry metadata for `retry_count` tracking).
  - Singleton: `pick_file_node = PickFileNode()`.
  - `ingestion_graph.py` rewritten to import `pick_file_node` from the new module and `ingestion_agent_node` from `ingestion_agent`, wiring `pick_file` → `ingest` → conditional routing (`_route_after_ingest`: loop back to `pick_file` if `files` or `retry_queue` non-empty, else `END`).
  - No test file directly imports `pick_file_node` — only exercised indirectly via `build_ingestion_graph().ainvoke(...)`, so no test edits needed; the patch target `second_brain.graphs.ingestion_graph.ingestion_agent_node` still resolves.
  - Commit: "refactor: extract pick_file_node into nodes/ as a BaseNode subclass".
- **Task 8 — `orchestrator.py` → `OrchestratorNode` (agent-based):**
  - Async `BaseAgentNode` subclass using `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)`. Caches `self._structured_llm = self._agent.get_model().with_structured_output(_RoutingOutput)` in `__init__`.
  - Routes queries into one of `"rag" | "web" | "both" | "neither"` based on the query and retrieved memory context, via a structured-output LLM call with a dedicated `_ROUTING_PROMPT`.
  - Singleton: `route_query = OrchestratorNode()`.
  - Test patch targets change from `second_brain.nodes.orchestrator._structured_llm` to `second_brain.nodes.orchestrator.route_query._structured_llm` (5 occurrences).
  - If basedpyright flags the `ClaudeAgent(...)`/`.with_structured_output(...)` calls, use the narrowest possible `# pyright: ignore[<code>]` matching existing file style (not a blanket ignore).
  - Commit: "refactor: convert orchestrator node to BaseAgentNode on ClaudeAgent".
- **Task 9 — `memory_agent.py` → `MemoryAgentNode` (agent-based):**
  - Async `BaseAgentNode` subclass on `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)`, caching `self._llm = self._agent.get_model().with_structured_output(MemoryAgentOutput)`.
  - Classifies user message into one of three `MemoryCase` values / prompt branches: (1) normal fact extraction, (2) correction check (when `awaiting_correction`), (3) conflict clarification (when `awaiting_conflict_clarification`) — each branch builds a different prompt.
  - `_prior_ai_content` helper (module-level, no `self`) finds the AI message preceding the last human message.
  - Contains the same "F1 fix" pattern: in Case 3, if the LLM omits `conflicts_with` UUIDs, copies them over from the previous turn's pending facts so persistence can still resolve conflicts.
  - Manages state-machine transitions: resets `awaiting_conflict_clarification`/`awaiting_correction`/`conflict_context` after conflict resolution; resets `awaiting_correction` after a correction turn.
  - Singleton: `memory_agent_node = MemoryAgentNode()`.
  - Test patch targets change from `second_brain.nodes.memory_agent._llm` to `second_brain.nodes.memory_agent.memory_agent_node._llm` (6 occurrences).
  - Commit: "refactor: convert memory_agent node to BaseAgentNode on ClaudeAgent".
- **Task 10 — `synthesis.py` → `SynthesisNode` (agent-based):**
  - Async `BaseAgentNode` subclass on `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET)` (note: SONNET, not HAIKU, unlike Tasks 8/9/11), caching `self._structured_llm = self._agent.get_model().with_structured_output(_SynthesisOutput)`.
  - `_format_messages` stays module-level (tests import it directly, doesn't touch `self`) — formats a message list into a readable "User:"/"Assistant:" transcript string, raising on multi-modal content.
  - Generates a final answer with confidence scoring: builds context sections from RAG results, web results, and retrieved memory; formats the last 10 messages of conversation history; builds a synthesis prompt; calls the structured LLM.
  - `_UNCERTAINTY_THRESHOLD = 0.7`; `_NEITHER_CONFIDENCE_FLOOR = 0.5` applied when `routing_decision == "neither"` (no external retrieval attempted, so confidence is floored since the LLM answered from context alone).
  - Singleton: `synthesize_answer = SynthesisNode()`.
  - Test patch targets change from `second_brain.nodes.synthesis._structured_llm` to `second_brain.nodes.synthesis.synthesize_answer._structured_llm` (11 occurrences).
  - Commit: "refactor: convert synthesis node to BaseAgentNode on ClaudeAgent".
- **Task 11 — `ingestion_agent.py` → `IngestionAgentNode`, remove dead code (genuine behavior change):**
  - Async `BaseAgentNode` subclass on `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)`, caching `self._model = self._agent.get_model()` (a plain `ChatAnthropic`, no structured output).
  - Genuine behavior change: header generation (`_generate_contextual_header`) moves off the raw `anthropic.AsyncAnthropic` SDK client onto `ClaudeAgent`/`ChatAnthropic` — this is the one piece of the whole refactor verified with a real test-first red/green cycle rather than a structural-move-only cycle.
  - The old test `test_generate_contextual_header_raises_when_no_text_block` (which asserted a `ValueError` on missing `TextBlock` from the raw SDK's response shape) is deleted and replaced with `test_generate_contextual_header_strips_whitespace`, which asserts the new `ChatAnthropic`-based response's `.content` string is stripped of leading/trailing whitespace.
  - `_generate_contextual_header`, `_process_one_chunk`, `_do_ingest` become instance methods (call `self._model`/`self._generate_contextual_header`/`self._process_one_chunk`/`self._do_ingest` transitively). `_sync_check_duplicate` and `_sync_write_results` stay module-level (no `self` dependency — pure SQLModel session writes).
  - `_do_ingest` flow: read file → hash content (MD5) → check duplicate via `_sync_check_duplicate` (rename to processed dir and return early if duplicate) → chunk document via `chunk_document` → process chunks concurrently bounded by `_CHUNK_SEMAPHORE` (`_CHUNK_CONCURRENCY = 10`) → write results via `_sync_write_results` → rename file to processed dir.
  - `__call__` (the LangGraph node): pulls `in_progress` filename from `IngestionState`, tracks retry count via `retry_queue`, calls `_do_ingest`, and on success returns updated `processed`/`in_progress`/`retry_queue`; on exception, either re-queues for retry (`next_count < MAX_RETRIES = 3`) or moves the file to `FAILED_DIR` and records it in `failed`.
  - Dead-code removal: `settings.ingestion_model` config field deleted from `config.py`; `ingestion_agent.shutdown()` and its two call sites in `main.py`'s `lifespan` teardown deleted (along with the `from second_brain.nodes import ingestion_agent` import in `main.py`).
  - Singleton: `ingestion_agent_node = IngestionAgentNode()`.
  - Multiple test patch-target updates required: unit test file (`test_ingestion_agent.py`) — 3 occurrences of `_generate_contextual_header` patches retargeted to `ingestion_agent_node._generate_contextual_header`; integration test file (`test_ingestion_graph.py`) — 3 occurrences (in `test_full_ingest_file_success`, `test_duplicate_file_is_skipped_on_reingest`, `test_api_endpoint_ingest_file_returns_correct_response`) retargeted similarly via an f-string `node` variable.
  - Integration tests require Postgres running (`just up-all` then `just test-integration`); if Postgres isn't available, the plan explicitly says to note that rather than assume success.
  - Commit: "refactor: convert ingestion_agent node to BaseAgentNode on ClaudeAgent, drop raw Anthropic client and dead shutdown/config".
- **Task 12 — Full-repo verification pass** (no file changes, verification only):
  - Confirms `apps/backend/src/second_brain/graphs/query_graph.py` needed zero edits across the whole refactor (`git diff main -- .../query_graph.py` should show no output) — proof that the naming/in-place-conversion rule held end-to-end.
  - Runs `just format lint type-check test-unit` for full workspace verification (expect no diffs from `format`, all green).
  - Runs integration verification (`just up-all && just test-integration`) if not already confirmed in Task 11.
  - Smoke-tests the running system: `curl -s -X POST localhost:3001/query -H 'Content-Type: application/json' -d '{"message": "Hello"}'` should return HTTP 200 with `final_answer`/`confidence` in the JSON body — confirms `query_graph.py`'s unchanged `add_node` calls resolve to the new class instances at runtime, not just at import/test time.
  - Final commit step for any stray formatting fixes surfaced by Step 2, using `git add -u` + a "chore: apply formatting fixes from full-repo verification pass" commit — skipped if nothing changed.
- Cross-cutting pattern across all agent-based nodes (Tasks 8-11): each node's `__init__` constructs its own `ClaudeAgent(CLAUDE_MODEL_NAME.<TIER>)` and derives a cached LLM handle (`_structured_llm` or `_llm` or `_model`) from `self._agent.get_model()`, so the graph files that call `add_node(name, instance)` never see or construct a model directly — this is the core architectural point of the whole refactor (nodes own their models, graphs stay model-agnostic).
- Cross-cutting test-patch-target pattern: whenever a module-level LLM handle becomes an instance attribute, every `unittest.mock.patch(...)` target in the corresponding test file must be updated from `second_brain.nodes.<module>.<attr>` to `second_brain.nodes.<module>.<singleton_name>.<attr>` — this repeats across Tasks 8 (5x), 9 (6x), 10 (11x), and 11 (3x unit + 3x integration).
- The plan is written for agentic/subagent-driven execution: it explicitly recommends `superpowers:subagent-driven-development` or `superpowers:executing-plans` skills, and uses checkbox (`- [ ]`) syntax per step for tracking progress task-by-task.
