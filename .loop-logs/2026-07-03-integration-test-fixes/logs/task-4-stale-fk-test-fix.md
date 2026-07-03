# Task 4 Log: Flip the stale FK tests to match the shipped migration (RC4)

## Task Context

### Plan Section
## Task 4: Flip the stale FK tests to match the shipped migration (RC4)

**Files:**

- Modify: `apps/backend/tests/integration/test_migration.py:121-132`

**Context:** Migration `002_drop_source_session_fk.py` (shipped in commit
`d9bbc69`) deliberately dropped the FK from `learned_facts`/
`model_corrections` to `chat_history` — "chat_history is never written by
the application". These two tests were never updated to match. Full detail:
`docs/bugs/003-integration-test-failures.md` Root Cause 4.

- [ ] **Step 1: Confirm the failure (red)**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_migration.py -v
```

Expected: `test_learned_facts_fk_to_chat_history` and
`test_model_corrections_fk_to_chat_history` FAIL — `"chat_history" in
referred` is false.

- [ ] **Step 2: Flip and rename the assertions**

Edit `apps/backend/tests/integration/test_migration.py`:

```python
# BEFORE (lines 121-132)
def test_learned_facts_fk_to_chat_history(db_engine):
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("learned_facts")
    referred = {fk["referred_table"] for fk in fks}
    assert "chat_history" in referred


def test_model_corrections_fk_to_chat_history(db_engine):
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("model_corrections")
    referred = {fk["referred_table"] for fk in fks}
    assert "chat_history" in referred

# AFTER
def test_learned_facts_no_fk_to_chat_history(db_engine):
    """Migration 002 dropped this FK — chat_history is never written by the app."""
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("learned_facts")
    referred = {fk["referred_table"] for fk in fks}
    assert "chat_history" not in referred


def test_model_corrections_no_fk_to_chat_history(db_engine):
    """Migration 002 dropped this FK — chat_history is never written by the app."""
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("model_corrections")
    referred = {fk["referred_table"] for fk in fks}
    assert "chat_history" not in referred
```

- [ ] **Step 3: Confirm the fix**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_migration.py -v
```

Expected: all tests in the file PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/test_migration.py
git commit -m "fix(test): assert learned_facts/model_corrections have no FK to chat_history

Migration 002 (d9bbc69) deliberately dropped this FK; these tests were
asserting the reversed, pre-migration design."
```

### Acceptance Criteria
- AC-5: `test_learned_facts_fk_to_chat_history` / `test_model_corrections_fk_to_chat_history` (renamed) assert `"chat_history" not in referred`

---

## Attempt 1 — 2026-07-03T06:18:03Z

### Implementation Plan
- Confirm red: run `test_migration.py` — expect `test_learned_facts_fk_to_chat_history` and `test_model_corrections_fk_to_chat_history` to FAIL since migration 002 already dropped the FK
- Flip and rename both tests exactly as specified in the plan (assert absence, add docstring referencing migration 002)
- Confirm green: full `test_migration.py` suite passes
- Run `just lint` and `just test-unit` to satisfy Done Means before committing

### Files Changed
- modified `apps/backend/tests/integration/test_migration.py` — renamed `test_learned_facts_fk_to_chat_history` → `test_learned_facts_no_fk_to_chat_history` and `test_model_corrections_fk_to_chat_history` → `test_model_corrections_no_fk_to_chat_history`; inverted assertion to `assert "chat_history" not in referred`; added docstrings citing migration 002

### New Tests
(none — pre-existing tests renamed and corrected, not new tests)

### Key Decisions
- No new dependencies or fixtures needed; `db_engine` fixture and `inspect()` usage were already correct — only the assertion polarity and test names were stale, per the plan/spec (AC-5), which explicitly sanctions this as a test-only correction matching an already-shipped migration (commit `d9bbc69`, migration `002_drop_source_session_fk.py`), not a "delete test to pass" violation
- Shortened the commit subject line from the plan's literal text (76 chars) to `fix(test): assert no chat_history FK on learned_facts/corrections` (65 chars) — the repo's `.hooks/commit-msg` enforces a 72-char subject limit; body text kept verbatim from the plan

### Lint Output
PASS
(`just lint` → "All checks passed!")

### Test Output
PASS (209 passed, 0 new — apps/backend unit suite via `just test-unit`)
PASS (10 passed, 0 new — `apps/backend/tests/integration/test_migration.py -v`, includes the 2 renamed/corrected tests)

### Commit
`c24ba48`

### Outcome: success
