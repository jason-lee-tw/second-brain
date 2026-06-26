# Task 8 Log: Integration Tests — Full Memory Loop

## Task Context

### Plan Section
Task 8: Integration Tests — Full Memory Loop

Files:
- Create: `apps/backend/tests/integration/test_memory_system.py`

Pre-condition: Docker stack running (`just up-all`) with live PostgreSQL+pgvector and Ollama. Tests skip automatically when `DATABASE_URL` doesn't point to a real DB.

### Acceptance Criteria
- AC-1: fact written to learned_facts with 1024-dim embedding
- AC-2: conflict detected, new fact not written
- AC-4: correction written to model_corrections with correction-field embedding
- Full loop: persist → retrieve via semantic search

---

## Attempt 1 — 2026-06-26T00:00:00Z

### Implementation Plan
- Check existing integration test skip guard pattern from test_migration.py
- Create test file with module-scoped db_engine fixture using same skip guard
- Add ensure_chat_session fixture for FK constraint (learned_facts.source_session → chat_history)
- Add clean_test_rows autouse fixture for test isolation
- Implement 4 tests: AC-1, AC-2, AC-4, full persist→retrieve loop

### Files Changed
- created `apps/backend/tests/integration/test_memory_system.py` — 4 integration tests

### New Tests
- `test_ac1_fact_written_to_db_with_embedding`
- `test_ac2_conflict_detected_not_written`
- `test_ac4_correction_written_with_embedding`
- `test_full_memory_loop_persist_then_retrieve`

### Key Decisions
- Skip guard matches test_migration.py pattern exactly for consistency
- `ensure_chat_session` module-scoped fixture creates required chat_history FK row before any test runs
- Integration tests use `pytestmark = pytest.mark.integration` for selective execution

### Lint Output
PASS

### Test Output
PASS (4 collected — skip without real DB)

### Commit
`2723d04`

### Outcome: success
