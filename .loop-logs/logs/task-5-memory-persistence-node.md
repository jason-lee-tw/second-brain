# Task 5 Log: memory_persistence_node — Fact + Correction Persistence

## Task Context

### Plan Section
Task 5: `memory_persistence_node` — Fact + Correction Persistence

Files:
- Create: `apps/backend/src/second_brain/nodes/memory_persistence.py`
- Create: `apps/backend/tests/unit/test_nodes/test_memory_persistence.py`

Interfaces:
- Consumes: `get_pgvector_pool()` (Task 1), `embed_text()`, `Session(engine)` from `db/session`, `LearnedFact` and `ModelCorrection` from `db/models`, `settings.memory_conflict_threshold` (Task 2)
- Produces: `memory_persistence_node(state) -> dict`

### Acceptance Criteria
- AC-1: fact_update → LearnedFact added to session with correct fields
- AC-2: conflicting fact → awaiting_conflict_clarification=True, fact NOT written
- AC-4: correction_update → ModelCorrection row; embed_text called with correction text
- Retry raises after 3 failures

---

## Attempt 1 — 2026-06-26T00:00:00Z

### Implementation Plan
- Write 5 unit tests covering AC-1, AC-1-skip-conflict-check, AC-2, AC-4, retry-raises
- Implement `_conflict_check` using asyncpg pool + settings.memory_conflict_threshold
- Implement `_retry_write`, `_write_fact`, `_write_correction` sync helpers
- Implement `_persist_fact` — checks `conflicts_with`, runs conflict check, writes or returns ConflictContext
- Implement `memory_persistence_node` — iterates facts and corrections, builds result dict

### Files Changed
- created `apps/backend/src/second_brain/nodes/memory_persistence.py` — tool-call node with conflict detection and per-fact retry
- created `apps/backend/tests/unit/test_nodes/test_memory_persistence.py` — 5 unit tests

### New Tests
- `test_ac1_writes_fact_with_embedding`
- `test_ac1_skips_conflict_check_when_conflicts_with_set`
- `test_ac2_detects_conflict_sets_state`
- `test_ac4_writes_correction_embedding_encodes_correction`
- `test_per_fact_retry_raises_after_three_failures`

### Lint Output
PASS

### Test Output
PASS (5 passed, 5 new)

### Commit
`f92f400`

### Outcome: success
