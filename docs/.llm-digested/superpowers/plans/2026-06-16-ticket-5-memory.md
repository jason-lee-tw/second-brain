# Memory System Implementation Plan

Source: docs/superpowers/plans/2026-06-16-ticket-5-memory.md
Primary-Topic: memory-system
Secondary-Topics: asyncpg-connection-pool, langgraph-query-graph

## Key Concepts

- **Goal**: Build the complete memory system for the Second Brain — shared asyncpg pool, auto fact extraction, conflict detection, model correction detection, cross-turn state machine, and a full `memory_retrieval_node` replacing the Ticket 4 stub.
- **Architecture flow**: `memory_retrieval_node` embeds the incoming query via `services/embeddings.embed_text()` and runs two parallel asyncpg cosine-similarity searches (learned facts + model corrections) to populate `retrieved_memory`. After synthesis, `memory_agent_node` (LangChain-Anthropic `with_structured_output(MemoryAgentOutput)`) classifies the user message into one of three `MemoryCase` values and populates `fact_updates` / `correction_updates`. `memory_persistence_node` (tool call, no LLM) then embeds each fact, conflict-checks via the asyncpg pool, and writes to the DB using SQLModel sync `Session(engine)` with per-fact retry × 3.
- **Tech stack**: Python 3.12, LangGraph, FastAPI, SQLModel, asyncpg, pgvector, LangChain-Anthropic (`ChatAnthropic.with_structured_output`), Ollama (`qwen3-embedding:0.6b`, dim=1024), pytest + pytest-asyncio, `unittest.mock`.

### Global constraints / design decisions (D1–D16)

- D1 — Embedding: always use `embed_text()` from `second_brain.services.embeddings` — never create a new embedding utility.
- D1 — asyncpg pool: always use `get_pgvector_pool()` from `second_brain.db.pool` — never a node-local pool.
- D2 — DB writes: SQLModel sync `Session(engine)` from `second_brain.db.session` — never `AsyncSession` for writes; DB reads (vector/cosine): asyncpg pool — never SQLAlchemy for pgvector cosine queries. Writes run directly (not `asyncio.to_thread`) since insert volume is 1–3 rows per turn at ~1–3ms each; comment flags to revisit if insert count grows.
- D11 — Message indexing: walk the `messages` list by type (`isinstance(msg, HumanMessage)` etc.), never use fixed negative indices.
- D3 — Conflict threshold: `settings.memory_conflict_threshold` (float, default 0.85, env `MEMORY_CONFLICT_THRESHOLD`) — never hardcode.
- D12 — Ollama errors: raise immediately — no empty-list fallback inside `memory_retrieval_node`.
- D4 — `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive — entering Case 3 (conflict resolution) resets `awaiting_correction=False`.
- D9 — `awaiting_correction=True` is set by the synthesis node (not the memory agent) when `confidence < 0.7`, alongside `is_uncertain`.
- asyncpg vector codec: `register_vector` (called by pool init) accepts a Python `list[float]` directly — no `pg_literal` string conversion needed.
- D10 — Node function name is `memory_retrieval_node` throughout (both the LangGraph node key AND the Python function name).
- D13 — reuse `embed_text()`; no new embedding utility.
- D5 — `ConflictContext` TypedDict carries `existing`, `existing_id`, `new`.
- D6 — per-fact retry × 3 attempts, then raise (no silent swallow).
- D7 — `conflicts_with` field on `FactUpdate` is reused to carry forward conflict IDs so Case 3 (conflict resolution) can resolve/rewrite the fact.
- D8 — `MemoryCase` (StrEnum: `fact_extraction`, `correction`, `conflict_resolution`) + `MemoryAgentOutput` (Pydantic model) produced via `ChatAnthropic.with_structured_output`.
- D15 — LangChain-Anthropic usage is scoped to the new memory nodes only; `ingestion_agent` is unchanged.
- D16 — integration tests must exercise the full loop against a real DB (skip guard when `DATABASE_URL` isn't a real running database, same pattern as `test_migration.py`).

### File map (what gets created/modified)

- Create `apps/backend/src/second_brain/db/pool.py` — asyncpg pool singleton shared by `rag_retrieval` and `memory_retrieval_node`.
- Modify `apps/backend/src/second_brain/nodes/rag_retrieval.py` — remove `_get_rag_pool`/`shutdown_rag_pool`; import pool from `db/pool.py`.
- Modify `apps/backend/src/second_brain/graphs/state.py` — add `ConflictContext`, `MemoryCase`, `MemoryAgentOutput`; update `conflict_context` type to `list[ConflictContext]`; add `awaiting_correction: bool` to `SynthesisNodeOutput`.
- Modify `apps/backend/src/second_brain/config.py` — add `memory_conflict_threshold: float = 0.85`.
- Modify `apps/backend/src/second_brain/nodes/memory_retrieval.py` — replace stub; rename function to `memory_retrieval_node`; use asyncpg pool + `embed_text`.
- Create `apps/backend/src/second_brain/nodes/memory_agent.py` — fact extraction + correction detection (3 cases) via LangChain-Anthropic structured output.
- Create `apps/backend/src/second_brain/nodes/memory_persistence.py` — asyncpg conflict-check reads + SQLModel sync writes; per-fact retry × 3.
- Modify `apps/backend/src/second_brain/nodes/synthesis.py` — set `awaiting_correction=True` alongside `is_uncertain` when `confidence < 0.7`.
- Modify `apps/backend/src/second_brain/graphs/query_graph.py` — wire the 3 new memory nodes after `redact_outbound`; rename `retrieve_memory` → `memory_retrieval_node`.
- Test files: `test_pool.py`, `test_state_and_config.py`, `test_memory_retrieval.py`, `test_memory_agent.py`, `test_memory_persistence.py`, `test_synthesis_awaiting.py`, `tests/integration/test_memory_system.py`.

### Task 1 — Shared asyncpg pool (`db/pool.py`)

- Produces `get_pgvector_pool() -> asyncpg.Pool` (singleton, created once, guarded by an `asyncio.Lock`) and `shutdown_pgvector_pool() -> None` (closes pool, resets singleton to `None`, no-op if never initialised).
- Pool `init=_setup_conn` calls `register_vector(conn)` (pgvector asyncpg codec) and sets a `jsonb` type codec (`json.dumps`/`json.loads`).
- `rag_retrieval.py`'s `_query_pgvector` drops its `postgres_url` param and calls `get_pgvector_pool()` instead of the old node-local `_get_rag_pool`.
- App lifespan (`main.py`) must replace `shutdown_rag_pool` calls with `shutdown_pgvector_pool` from `db/pool.py`.
- CLAUDE.md's "Two Postgres connection pools" note updated to describe `db/pool.py` as shared by `rag_retrieval` + `memory_retrieval_node`, versus the separate `psycopg_pool.AsyncConnectionPool` in `query_graph.py` used by LangGraph's `AsyncPostgresSaver` (different drivers, cannot share a pool).
- Tests: pool singleton returns same instance across two calls; shutdown closes and resets; shutdown is a no-op when pool is `None`.

### Task 2 — State schema + config updates

- `ConflictContext` TypedDict: `existing: str`, `existing_id: str`, `new: str`.
- `MemoryCase` StrEnum: `FACT_EXTRACTION = "fact_extraction"`, `CORRECTION = "correction"`, `CONFLICT_RESOLUTION = "conflict_resolution"`.
- `MemoryAgentOutput` Pydantic model: `case: MemoryCase`, `fact_updates: list[FactUpdate] = []`, `correction_updates: list[CorrectionUpdate] = []`.
- `SecondBrainState.conflict_context` type changes from `NotRequired[list[str]]` to `NotRequired[list[ConflictContext]]`.
- `Settings.memory_conflict_threshold: float = 0.85` added near other model-behaviour settings (after `embedding_model`).

### Task 3 — `memory_retrieval_node` full implementation

- Finds the last `HumanMessage` by walking `state["messages"]` in reverse (never fixed indices); if none found, returns `{"retrieved_memory": []}`.
- Embeds the query text via `embed_text()` — this call is allowed to raise (Ollama down ⇒ propagate `ValueError`, no fallback).
- Runs `_search_facts` and `_search_corrections` concurrently via `asyncio.gather`, each acquiring its own connection from the shared pool (asyncpg connections are not shared across coroutines).
- `_search_facts`: `SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score FROM learned_facts ORDER BY embedding<=>$1 ASC LIMIT 5`; `MemoryItem(type="learned_fact")` keeps the row's real `confidence`.
- `_search_corrections`: `SELECT id::text, correction AS fact, 1-(embedding<=>$1) AS score FROM model_corrections ORDER BY embedding<=>$1 ASC LIMIT 3`; `MemoryItem(type="model_correction")` is always given `confidence=1.0` (corrections are treated as ground truth).
- Results from both searches are merged and sorted descending by score before being returned as `retrieved_memory`.
- Query ordering uses the raw `<=>` distance operator ascending (not `1-(...)` descending) so the pgvector HNSW/IVFFlat index is actually used; the `1-distance` score is computed only in the `SELECT` list.

### Task 4 — `memory_agent_node` (three MemoryCase branches)

- Uses `ChatAnthropic(model="claude-haiku-4-5").with_structured_output(MemoryAgentOutput)` as a module-level `_llm`.
- `_last_human_msg` walks messages in reverse for the latest `HumanMessage`; if none, returns empty `fact_updates`/`correction_updates`.
- `_prior_ai_content` finds the `AIMessage` immediately preceding the latest `HumanMessage` (for correction-case context).
- Branch selection based on state flags (checked in this priority order): `awaiting_conflict_clarification` → Case 3 (conflict_resolution); else `awaiting_correction` → Case 2 (correction); else → Case 1 (fact_extraction).
- **Case 1 (fact_extraction)**: prompts the LLM to extract self-referential facts (e.g. "I work as X", "I live in Y", "I prefer Z") from the user's message; returns empty `fact_updates` if none; every fact gets `conflicts_with=[]`.
- **Case 2 (correction)**: given the prior uncertain AI answer + the user's response, the LLM decides between `case=correction` (populates `correction_updates` with `original_answer`, `correction`, `root_cause`) or falls back to `case=fact_extraction` if the user asked something unrelated instead of correcting. After this branch runs, `awaiting_correction` is always reset to `False` (whether or not a correction was actually detected) — this is AC-3.
- **Case 3 (conflict_resolution)**: given the pending `conflict_context` entries and the user's clarification, the LLM populates `fact_updates` with the resolved fact(s) (or empty list if the user chose to "keep existing" — nothing to write) and sets `conflicts_with=[]` since persistence handles deletion of the old fact. After this branch, both `awaiting_conflict_clarification` and `awaiting_correction` are reset to `False` (D4 mutual exclusivity) and `conflict_context` is reset to `[]`.
- Output dict always includes `fact_updates` and `correction_updates` (copied lists from the LLM output), plus the state-machine flag resets appropriate to the branch taken.

### Task 5 — `memory_persistence_node` (tool-call node, no LLM)

- `_conflict_check(embedding)`: queries `learned_facts` for rows within threshold, using the distance-domain predicate `(embedding<=>$1) < (1 - settings.memory_conflict_threshold)` (so the pgvector index can be used), ordered by distance ascending, limit 5.
- `_retry_write(fn, *args)`: runs a sync write function up to `_MAX_RETRIES=3` times, catching all exceptions except on the final attempt, where it re-raises — used for both fact and correction writes.
- `_write_fact` / `_write_correction`: open `Session(engine)` (SQLModel sync), `session.add(...)`, `session.commit()`. Comment notes these run directly on the event loop (not `asyncio.to_thread`) because volume is low (1–3 inserts/turn, ~1–3ms each) — flagged to revisit if insert count grows.
- `LearnedFact` row fields: `id` (new UUID), `fact`, `embedding`, `source_session` (= `state["session_id"]`), `confidence`.
- `ModelCorrection` row fields: `id` (new UUID), `original_answer`, `correction`, `root_cause`, `embedding`, `source_session`. **Critically, the embedding encodes the `correction` field, not `original_answer`** — so cosine retrieval surfaces the corrected fact, not the mistake (matches CLAUDE.md's documented pattern).
- `_persist_fact(fact_update, session_id)`: embeds the fact text; if `fact_update["conflicts_with"]` is already non-empty (user already resolved a prior conflict), writes directly and skips the conflict check entirely (no `fetch()` call made). Otherwise runs `_conflict_check`; if any conflicting rows are found, returns a `ConflictContext` (using the top/first conflict row) instead of writing; otherwise writes and returns `None`.
- `memory_persistence_node(state)`: iterates `fact_updates`, calling `_persist_fact` for each; any that produce a `ConflictContext` are collected, and the fact itself is re-queued in `pending_facts` with `conflicts_with=[conflict["existing_id"]]` so Case 3 can later resolve it. Iterates `correction_updates`, embedding `correction["correction"]` (not `original_answer`) and writing via `_write_correction` (no conflict check for corrections). Returns a dict setting `awaiting_conflict_clarification` (True iff any conflicts found), `conflict_context` (list of ConflictContext), `fact_updates` (the pending/conflicted ones, or `[]` if none conflicted — successfully written facts are NOT re-returned), and `correction_updates=[]`. If conflicts were found, appends a "⚠️ I noticed potential conflicts with existing memory..." block (listing each existing vs. new fact) to `final_answer` and asks the user to clarify.
- Per-fact retry failure (all 3 attempts of `_write_fact`/`_write_correction` raise) propagates the underlying exception out of `memory_persistence_node` — no silent failure.

### Task 6 — Synthesis node update

- `SynthesisNodeOutput` TypedDict gains `awaiting_correction: bool` alongside `final_answer`, `confidence`, `is_uncertain`.
- `synthesize_answer`'s return dict computes `is_uncertain = confidence < _UNCERTAINTY_THRESHOLD` (threshold is 0.7) and sets `awaiting_correction` to the same boolean — i.e., whenever the AI's answer confidence drops below 0.7, the graph enters a state expecting the next user turn to possibly be a correction (Case 2 in the memory agent).

### Task 7 — Wiring into the query graph

- Imports change from a single `retrieve_memory` import to three: `memory_agent_node`, `memory_persistence_node`, `memory_retrieval_node`.
- Graph nodes: `memory_retrieval_node` registered under key `"memory_retrieval_node"` (same name as the function, D10); `memory_agent` and `memory_persistence` registered as separate graph nodes running `memory_agent_node`/`memory_persistence_node`.
- Edge rewiring: `redact_inbound → memory_retrieval_node → orchestrator` (was `redact_inbound → retrieve_memory → orchestrator`); and at the tail, `redact_outbound → memory_agent → memory_persistence → END` (previously `redact_outbound → END` directly) — so every query turn now runs fact/correction extraction and persistence after the answer is redacted, before the turn completes.

### Task 8 — Integration tests (full memory loop against real DB)

- Requires the Docker stack (`just up-all`) with live PostgreSQL+pgvector and Ollama; tests are marked `pytest.mark.integration` and skip automatically when `DATABASE_URL` doesn't point at a real DB (same skip guard pattern as `test_migration.py`: skip if `"test-api-key"` is in the URL or neither `"localhost"` nor `"app_postgres"` appears in it).
- A `clean_test_rows` autouse fixture deletes any `learned_facts`/`model_corrections` rows tagged with the fixed test session id (`"integration-memory-test"`) before each test, to keep tests independent.
- AC-1 test: writes two facts via `memory_persistence_node`, then asserts each `learned_facts` row has a 1024-dim, non-all-zero embedding.
- AC-2 test: pre-seeds a `learned_facts` row ("The user lives in Berlin."), then attempts to persist a semantically similar new fact ("The user lives in Berlin now.") — asserts `awaiting_conflict_clarification is True`, the `⚠️` marker is appended to `final_answer`, and the new fact was NOT written to the DB.
- AC-3 is intentionally NOT re-tested at the integration level — it's covered purely by the unit test `test_case2_unrelated_query_resets_awaiting_correction` in `test_memory_agent.py`, since it doesn't require a real DB.
- AC-4 test: persists a correction and asserts the `model_corrections` row's `correction` field contains the corrected text, `root_cause` matches, and the embedding is a real 1024-dim vector.
- Full-loop test: persists a fact ("The user is a professional cyclist.") in one call, then calls `memory_retrieval_node` with an unrelated-phrasing but semantically related query ("What sports do I do?") and asserts the fact is present in `retrieved_memory` (proves persist→embed→retrieve round-trips correctly end to end).

### Self-review / spec coverage notes (from the plan's own checklist)

- The plan maps every acceractual criterion (AC-1 through AC-4) and design decision (D1–D16) to the task that implements/tests it — see the "Spec coverage" and "Type consistency" tables at the end of the source plan for the full traceability matrix.
- Explicitly calls out "No TBDs, TODOs, or 'similar to' references — all code blocks are complete and runnable" as a self-review criterion (placeholder scan).
- Recommended sub-skill for agentic workers executing this plan: `superpowers:subagent-driven-development` (preferred) or `superpowers:executing-plans`, working task-by-task using the checkbox (`- [ ]`) syntax embedded throughout the plan.
