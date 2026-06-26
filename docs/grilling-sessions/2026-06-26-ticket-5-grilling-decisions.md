# Ticket 5 Memory System — Grilling Session Decisions

**Date:** 2026-06-26  
**Context:** Pre-implementation grilling of `2026-06-16-ticket-5-memory.md` plan and `2026-06-16-second-brain-design.md` spec. PR #7 (feat/005-memory) was closed; PRs #8–11 introduced patterns that conflict with the original plan.

---

## Issues Found in Original Plan

| Issue                                                                                                  | Impact                               |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| `memory_retrieval.py` created its own `AsyncSessionLocal` (SQLAlchemy) — wrong driver for pgvector     | Critical — pgvector requires asyncpg |
| `asyncio.gather` with shared `AsyncSession` — not concurrency-safe                                     | Bug                                  |
| Function name `memory_retrieval_node` vs stub `retrieve_memory` — mismatch                             | Plan/code drift                      |
| `_last_human_content()` silently returns `""` on multi-modal — wrong vs `get_str_content()` convention | Inconsistency                        |
| `DATABASE_URL` env var read directly — should use `settings.postgres_url`                              | Inconsistency                        |
| `conflict_context: list[str]` — too weak for user to act on                                            | API design gap                       |
| File map missing `db/pool.py`, `state.py` changes, `config.py` changes, `rag_retrieval.py` changes     | Incomplete                           |

---

## Decisions

### D1 — asyncpg Pool Architecture

**Decision:** Move asyncpg pool singleton to `second_brain/db/pool.py`.  
**Why:** `memory_retrieval` and `rag_retrieval` both query pgvector tables; sharing from `db/pool.py` avoids two independent pools for the same purpose. A node depending on another node (`rag_retrieval`) for its pool is wrong coupling.  
**Impact:** Create `db/pool.py` with `get_pgvector_pool()` and `shutdown_pgvector_pool()`. Remove `_get_rag_pool()` and `shutdown_rag_pool()` from `rag_retrieval.py`. App lifespan imports shutdown from `db/pool.py`.

### D2 — MemoryPersistenceNode DB Writes

**Decision:** SQLModel sync `Session` (matching `ingestion_agent` pattern) for writes; asyncpg pool for conflict-check reads.  
**Why:** `LearnedFact` and `ModelCorrection` SQLModel models already exist in `db/models.py`. Using them for writes keeps ORM models and runtime code consistent. `ingestion_agent` already uses this pattern. 1–3 inserts per turn — event-loop block is negligible.  
**Documented in:** `docs/codebase/003-database-management.md`

### D3 — Conflict Threshold in Settings

**Decision:** `memory_conflict_threshold: float = 0.85` added to `Settings` in `config.py`, read from env var `MEMORY_CONFLICT_THRESHOLD`.  
**Why:** Eval tooling needs to adjust at runtime without code deploys.

### D4 — Mutually Exclusive State Flags

**Decision:** `awaiting_correction` and `awaiting_conflict_clarification` are mutually exclusive. When conflict clarification is set, `awaiting_correction` is reset to `False`.  
**Why:** Conflict affects data integrity; correction affects answer quality. Conflict takes priority.

### D5 — `conflict_context` Type Change

**Decision:** `conflict_context: list[str]` → `list[ConflictContext]` in `SecondBrainState`.  
**ConflictContext shape:**

```python
class ConflictContext(TypedDict):
    existing: str       # text of the existing fact
    existing_id: str    # UUID of the existing learned_fact row
    new: str            # text of the proposed new fact
```

**Why:** User must read the conflict and reply; structured objects are actionable; bare strings are not.  
**Breaking change:** `/query` response `conflictContext` field changes from `list[str]` to `list[object]`.

### D6 — MemoryPersistenceNode Failure Strategy

**Decision:** Per-fact retry (up to 3 attempts each), then raise — failing the entire node.  
**Why:** Per-fact retry avoids duplicate writes on partial success. Silent partial writes create invisible memory gaps — worse than a surfaced error. LangGraph checkpoint preserves `fact_updates` so a retry can re-attempt.

### D7 — Conflict Resolution Output

**Decision:** Reuse `FactUpdate` with `conflicts_with: [existing_id]`.  
**Why:** `conflicts_with` was designed for this. `MemoryPersistenceNode` already handles it: delete IDs in `conflicts_with`, insert the new fact. No new TypedDicts needed.

### D8 — MemoryAgentOutput Schema

**Decision:** Use `MemoryCase` (`StrEnum`) + `with_structured_output` via LangChain-Anthropic.

```python
class MemoryCase(StrEnum):
    FACT_EXTRACTION = "fact_extraction"
    CORRECTION = "correction"
    CONFLICT_RESOLUTION = "conflict_resolution"

class MemoryAgentOutput(BaseModel):
    case: MemoryCase
    fact_updates: list[FactUpdate] = []
    correction_updates: list[CorrectionUpdate] = []
```

**Why:** `case` field makes logic explicit and testable. `StrEnum` eliminates magic strings at comparison sites. `with_structured_output` avoids manual tool-call parsing.  
**`MemoryCase` lives in:** `graphs/state.py`

### D9 — Who Sets `awaiting_correction=True`

**Decision:** Synthesis sets both `is_uncertain=True` and `awaiting_correction=True` when `confidence < 0.7`.  
**Why:** Synthesis already holds `confidence`; setting both in one return dict is clean. Delegating to `MemoryPersistenceNode` would give it a non-memory concern.

### D10 — Node Naming

**Decision:** `memory_retrieval_node` (not `retrieve_memory`). Graph wiring updated: `workflow.add_node("memory_retrieval_node", memory_retrieval_node)`.

### D11 — MemoryAgent Message Indexing

**Decision:** Walk `messages` by type to find the last `HumanMessage` and prior `AIMessage` — no fixed negative indices.  
**Why:** Fixed indices break when `redact_outbound` appends the current AI answer before memory nodes run.

### D12 — Ollama Unavailability in `memory_retrieval_node`

**Decision:** Fail hard (raise) — do not return empty `retrieved_memory`.  
**Why:** Memory is load-bearing in this system. Silent degradation would produce answers with no memory context, violating the system's purpose.

### D13 — Embedding utility — use `services/embeddings.embed_text()`

**Decision:** Memory nodes import `embed_text` from the existing `second_brain/services/embeddings.py`. Do NOT create `utils/embedding.py`.  
**Why:** `services/embeddings.py` already exists with a persistent `httpx.AsyncClient`, `settings.ollama_base_url`, `settings.embedding_model`, and proper error handling — it is strictly better than the `utils/embedding.py` proposed in the original plan. The original plan was unaware of it.  
**Original plan issue corrected:** Plan proposed creating `utils/embedding.py` with `get_embedding()` and `embedding_to_pg_literal()`. Both are unnecessary — `embed_text()` already uses `settings`, and asyncpg's registered vector codec accepts a Python list directly (no `pg_literal` string needed).

### D14 — Embedding Unification Ticket (revised)

**Decision:** A separate ticket will extract `rag_retrieval._embed_query()` and unify it to use `services/embeddings.embed_text()`. Plan that ticket together before implementation.  
**Why:** YAGNI — don't refactor `rag_retrieval.py` as a side-effect of ticket 5. But `rag_retrieval._embed_query()` is now duplicated logic given `services/embeddings.embed_text()` exists.

### D15 — LangChain-Anthropic (scope: new memory nodes only)

**Decision:** New memory nodes created in this ticket (`memory_agent.py`) use LangChain-Anthropic (`ChatAnthropic` + `.with_structured_output()`). Existing nodes are not changed.  
**Why:** `with_structured_output` avoids manual tool-call parsing for `MemoryAgentOutput`. Scope is limited to new nodes — `ingestion_agent.py` uses the direct Anthropic SDK (`anthropic.AsyncAnthropic`) and is not subject to this decision.

### D16 — Integration Test

**Decision:** Real DB (same fixture pattern as `tests/integration/test_migration.py`).  
**Why:** Cosine similarity, pgvector `<=>` operator, embedding round-trip, and conflict threshold behaviour are only meaningful against a real DB.

---

## New Ticket Required

**Ticket: Unify embedding utility**  
`services/embeddings.embed_text()` already exists and is the canonical embedding helper. `rag_retrieval.py` still has a duplicate `_embed_query()` inline. The new ticket replaces `_embed_query()` with `embed_text()` from `services/embeddings`. Plan this ticket together before implementation.
