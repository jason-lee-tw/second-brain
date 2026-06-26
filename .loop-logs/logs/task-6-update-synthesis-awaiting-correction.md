# Task 6 Log: Update synthesis.py — Set awaiting_correction

## Task Context

### Plan Section
Task 6: Update `synthesis.py` — Set `awaiting_correction`

Files:
- Modify: `apps/backend/src/second_brain/nodes/synthesis.py`
- Create: `apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py`

Interfaces:
- Change: synthesis return dict now includes `awaiting_correction: bool` alongside `is_uncertain`

### Acceptance Criteria
- D9: confidence < 0.7 → is_uncertain=True AND awaiting_correction=True
- confidence >= 0.7 → is_uncertain=False AND awaiting_correction=False

---

## Attempt 1 — 2026-06-26T00:00:00Z

### Implementation Plan
- Write 2 unit tests: one for uncertain (confidence=0.5), one for confident (confidence=0.95)
- Read synthesis.py to find the return statement
- Extract `is_uncertain` variable and add `awaiting_correction: is_uncertain` to return dict

### Files Changed
- modified `apps/backend/src/second_brain/nodes/synthesis.py` — add `awaiting_correction` to return
- created `apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py` — 2 unit tests

### New Tests
- `test_synthesis_sets_awaiting_correction_when_uncertain`
- `test_synthesis_does_not_set_awaiting_correction_when_confident`

### Key Decisions
- `is_uncertain` extracted to local variable so both `is_uncertain` and `awaiting_correction` share the same threshold check without duplication

### Lint Output
PASS

### Test Output
PASS (2 passed, 2 new)

### Commit
`5cc608b`

### Outcome: success
