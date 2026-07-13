# Memory System

The Second Brain's long-term memory is two pgvector-backed tables (`learned_facts`, `model_corrections`) written and read every `/query` turn by three LangGraph nodes, governed by a mutually-exclusive cross-turn state machine for conflicts and corrections.

## Key Concepts

- **Purpose**: auto-extract facts the user states about themselves and detect when the user corrects a low-confidence answer, so both persist as long-term memory retrievable in future turns via semantic search — this is what lets the Second Brain improve over a stateless no-RAG baseline.
- **Data model** — two tables (both `VECTOR(1024)` to match the `qwen3-embedding:0.6b` Ollama model):
  - `learned_facts`: `id`, `fact` (TEXT, PII-scrubbed), `embedding`, `source_session` (UUID7, no longer FK-constrained to `chat_history` — see [[database-schema]]), `confidence`, `created_at`/`updated_at`.
  - `model_corrections`: `id`, `original_answer`, `correction`, `root_cause`, `embedding`, `source_session`, `created_at`. The embedding column encodes the `correction` field, **not** `original_answer` — deliberate, so cosine-similarity retrieval surfaces the corrected fact rather than the mistake.
- **Three query-graph nodes** own the memory lifecycle end to end (see [[query-graph]] / [[query-workflow]]):
  1. `memory_retrieval_node` (renamed from an earlier `retrieve_memory` stub, D10) — runs near the start of the graph, before the Orchestrator. Embeds the incoming query via `embed_text()` (`second_brain/services/embeddings.py` — never a new embedding utility, D13) and runs two concurrent asyncpg cosine-similarity searches over `learned_facts` (top-5) and `model_corrections` (top-3, always `confidence=1.0` — treated as ground truth) using the shared pool from `db/pool.py` (`get_pgvector_pool()`, D1; see [[postgres-connection-pooling]] and [[pgvector-embeddings]]). Results are merged, sorted by score, returned as `retrieved_memory`. If Ollama is unavailable, it raises rather than returning an empty list (D12) — memory is load-bearing, so silent degradation is worse than a visible failure.
  2. `memory_agent_node` — runs after Synthesis and outbound PII redaction. Uses `ChatAnthropic("claude-haiku-4-5").with_structured_output(MemoryAgentOutput)` (LangChain-Anthropic, scoped to only the new memory nodes — `ingestion_agent.py` keeps using the raw Anthropic SDK, D15) to classify the turn into one of three `MemoryCase` branches (checked in priority order): `CONFLICT_RESOLUTION` (if `awaiting_conflict_clarification`), then `CORRECTION` (if `awaiting_correction`), then `FACT_EXTRACTION` (default). It walks `state["messages"]` by type (`isinstance(msg, HumanMessage)`, etc.) to find the latest human message and the prior AI message, rather than using fixed negative indices (D11) — indices break because outbound redaction already appended the current AI answer.
  3. `memory_persistence_node` — a tool-call node, no LLM. Reads via the asyncpg pool (conflict-check), writes via SQLModel's sync `Session(engine)` (D2 — mirrors the existing `ingestion_agent` pattern; write volume is only 1-3 rows/turn so blocking the event loop briefly is accepted, flagged to revisit if volume grows). Each fact/correction write retries up to 3 times before the node raises and fails outright — no silent partial writes (D6).
- **Fact lifecycle**: `FACT_EXTRACTION` pulls self-referential statements ("I work as X", "I live in Y") into `fact_updates`. `memory_persistence_node` embeds each fact and conflict-checks it against existing `learned_facts` using `settings.memory_conflict_threshold` (default `0.85`, env `MEMORY_CONFLICT_THRESHOLD`, D3) via a distance-domain predicate on the raw `<=>` operator (so the pgvector index is used). No conflict → write. Conflict → return a `ConflictContext` instead of writing, re-queue the fact with `conflicts_with=[existing_id]` (reusing the existing `FactUpdate.conflicts_with` field rather than inventing a new type, D7), and surface the conflict in `final_answer`. Next turn, `CONFLICT_RESOLUTION` resolves it — deletes the conflicting row(s) and writes the resolved fact.
- **Correction lifecycle**: `Synthesis` (not the memory agent, D9 — it already holds `confidence` in scope) sets `is_uncertain=True` AND `awaiting_correction=True` together whenever `confidence < 0.7`. On the next turn: if the user's message is a correction, `CORRECTION` extracts `original_answer` + `correction` + `root_cause` into `correction_updates`; if it's an unrelated query instead, the branch just resets `awaiting_correction=False` and falls back to normal fact extraction (AC-3). Either way `awaiting_correction` is always reset to `False` after this branch runs. Corrections are written with no conflict check.
- **State flag invariant**: `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive (D4) — entering `CONFLICT_RESOLUTION` always resets `awaiting_correction=False` first, because a data-integrity conflict takes priority over an answer-quality correction.
- **Key TypedDicts/models** (`graphs/state.py`): `MemoryItem` (id, fact, confidence, `type: Literal["learned_fact","model_correction"]`), `FactUpdate` (fact, confidence, `conflicts_with: list[str]`), `CorrectionUpdate` (original_answer, correction, root_cause), `ConflictContext` (existing, existing_id, new), `MemoryCase` StrEnum (`fact_extraction`, `correction`, `conflict_resolution`), `MemoryAgentOutput` (case, fact_updates, correction_updates). `SecondBrainState.conflict_context` is `list[ConflictContext]`, changed from an earlier `list[str]` (D5) because the user must be able to read and act on a conflict — a bare string isn't actionable. This is a breaking API change: the `/query` response's `conflictContext` field goes from `list[str]` to `list[object]`.
- **API surface mapping**: `isUncertain` ← `is_uncertain`; `conflictDetected` ← `awaiting_conflict_clarification`; `conflictContext` ← `conflict_context`. See [[second-brain-architecture]] for the full `/query` contract.
- **Shared asyncpg pool**: `memory_retrieval_node` and `rag_retrieval` both read pgvector via the same `get_pgvector_pool()`/`shutdown_pgvector_pool()` singleton in `db/pool.py` rather than each owning an independent pool — a memory node depending on the RAG node's pool would be backwards coupling. This asyncpg pool is distinct from the `psycopg_pool.AsyncConnectionPool` LangGraph's `AsyncPostgresSaver` uses for checkpointing — different drivers, cannot be merged. See [[postgres-connection-pooling]].
- **PII interaction**: inbound/outbound PII redaction nodes run outside the memory nodes (inbound before `memory_retrieval_node`, outbound before `memory_agent_node`), so facts stored in `learned_facts` are already PII-scrubbed by the time the memory agent sees the message.
- **Deferred/out-of-scope**: unifying `rag_retrieval.py`'s duplicate inline `_embed_query()` with the canonical `embed_text()` was explicitly deferred to a separate future ticket (D14) — YAGNI, don't refactor `rag_retrieval.py` as a side effect of building the memory system.

## Known Issues Fixed Post-Ship

Two of the four root causes fixed in the 2026-07-03 integration-test-fixes effort (see [[integration-testing]]) were memory-system bugs, found only once the real DB/Ollama stack was exercised end to end:

- **Conflict threshold silently disabled**: `_conflict_check`'s SQL computed `(embedding<=>$1) < (1 - $2)`, and because `$2` (the threshold, e.g. `0.85`/`0.95`) only ever appeared inside `1 - $2`, Postgres inferred `$2` as `integer` from the untyped literal `1`, so asyncpg truncated the real float threshold to `0` — the WHERE clause became `distance < 1`, matching almost any two facts as conflicting. Fixed by precomputing `max_distance = 1 - threshold` in Python and binding it directly, so the SQL is just `(embedding<=>$1) < $2`. Verified against real embeddings: "vegetarian" vs "hiking" (similarity 0.60) → no conflict; "Berlin" vs "Berlin now" (similarity 0.97) → conflict.
- **Raw-SQL test fixture couldn't decode the pgvector column**: SQLModel's ORM path gets the pgvector codec for free via `pgvector.sqlalchemy.Vector`, but a raw-SQL integration-test fixture reading `learned_facts`/`model_corrections` outside the ORM had no codec registered, so embedding columns came back as a 12764-character text literal instead of a 1024-dim `list[float]`. Fixed by registering `pgvector.psycopg2.register_vector` on the SQLAlchemy engine's `connect` event.
- Separately, `test_migration.py` had two stale tests asserting `learned_facts`/`model_corrections` still had a foreign key to `chat_history` — migration `002_drop_source_session_fk.py` had already intentionally dropped it (since `chat_history` is never written by the app). The tests were renamed and flipped to assert the FK's absence rather than the schema being changed.
- Integration tests for the memory system require a real DB (`just up-all`, live Postgres + Ollama), following the `test_migration.py` fixture/skip-guard pattern, because cosine similarity, the `<=>` operator, embedding round-trips, and conflict-threshold behavior are only meaningful against a real database (D16).

## Open Questions

- **memory_conflict_threshold default**: this page states the default is `0.85`, but [[integration-testing]] and [[pgvector-embeddings]] describe the same conflict-check code path with the value bound as `0.95`. Unresolved — needs source verification.
- **MemoryCase branch count**: this page says classification uses three `MemoryCase` branches; [[query-workflow]] says four (though only lists three). Unresolved.

## Sources

- Project Requirement Document — Second Brain — `docs/business/002-project-requirement-document.md`
- Workflow Design — `docs/business/004-workflow-design.md`
- Ticket 5 Memory System — Grilling Session Decisions — `docs/grilling-sessions/2026-06-26-ticket-5-grilling-decisions.md`
- Memory System Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-5-memory.md`
- Fix `just test-integration` Implementation Plan — `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`
- Second Brain — System Design Spec — `docs/superpowers/specs/2026-06-16-second-brain-design.md`
- Spec: Fix `just test-integration` failures (4 independent root causes) — `docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md`

## Related Topics

- [[second-brain-architecture]]
- [[second-brain-requirements]]
- [[query-graph]]
- [[query-workflow]]
- [[database-schema]]
- [[pgvector-embeddings]]
- [[postgres-connection-pooling]]
- [[integration-testing]]
- [[database-access-patterns]]
- [[known-issues]]
- [[capstone-requirements]]
- [[implementation-plan]]
