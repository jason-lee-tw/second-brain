# Task 3 Log: Fix the conflict-check threshold type coercion (RC1)

## Task Context

### Plan Section
## Task 3: Fix the conflict-check threshold type coercion (RC1)

**Files:**

- Modify: `apps/backend/src/second_brain/nodes/memory_persistence.py:28-41`

**Context:** `_conflict_check`'s SQL does `(1 - $2)` where `$2` is the only
occurrence of the threshold parameter. Postgres infers `$2`'s type from the
untyped literal `1` (→ `integer`), so asyncpg truncates the real threshold
(`0.95`) to `0`, making the WHERE clause `distance < 1` — nearly any two
facts "conflict". Full detail: `docs/bugs/003-integration-test-failures.md`
Root Cause 1. Verified fix produces correct behavior against real
embeddings: "vegetarian" vs "hiking" (similarity 0.60) → no conflict;
"Berlin" vs "Berlin now" (similarity 0.97) → conflict.

- [ ] **Step 1: Confirm the failure (red)**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py::test_ac1_fact_written_to_db_with_embedding -v
```

Expected: FAIL with `AssertionError: assert 1 == 2` (the second fact is
wrongly treated as conflicting with the first).

- [ ] **Step 2: Apply the fix**

Edit `apps/backend/src/second_brain/nodes/memory_persistence.py`:

```python
# BEFORE (lines 28-41)
async def _conflict_check(embedding: list[float]) -> list[dict[str, Any]]:
    """Return rows from learned_facts whose cosine similarity exceeds threshold."""
    threshold = settings.memory_conflict_threshold
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
            " FROM learned_facts"
            " WHERE (embedding<=>$1) < (1 - $2)"
            " ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
            threshold,
        )
        return [dict(r) for r in rows]

# AFTER
async def _conflict_check(embedding: list[float]) -> list[dict[str, Any]]:
    """Return rows from learned_facts whose cosine similarity exceeds threshold."""
    threshold = settings.memory_conflict_threshold
    max_distance = 1 - threshold
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
            " FROM learned_facts"
            " WHERE (embedding<=>$1) < $2"
            " ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding,
            max_distance,
        )
        return [dict(r) for r in rows]
```

- [ ] **Step 3: Confirm the fix**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py -v
```

Expected: `test_ac1_fact_written_to_db_with_embedding`,
`test_ac2_conflict_detected_not_written`, and
`test_full_memory_loop_persist_then_retrieve` all PASS. `test_ac2` passing
confirms the fix didn't just disable the check entirely — a real conflict
("Berlin" vs "Berlin now", 0.97 similarity) is still caught.

- [ ] **Step 4: Run type-check (return type/signature unchanged, but confirm no regressions)**

```bash
just type-check
```

Expected: no errors or warnings.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/memory_persistence.py
git commit -m "fix(memory): bind precomputed max-distance in conflict-check SQL

The threshold parameter only appeared inside \`1 - \$2\`, so Postgres inferred
its type from the untyped literal 1 (integer), truncating the real 0.95
threshold to 0. This disabled the conflict check entirely."
```

### Acceptance Criteria
- AC-1: `_conflict_check` with threshold `0.95` does not flag "The user is a vegetarian." vs "The user loves hiking." (cosine similarity 0.60) as a conflict
- AC-2: `_conflict_check` with threshold `0.95` does flag "The user lives in Berlin." vs "The user lives in Berlin now." (cosine similarity 0.97) as a conflict

---

## Attempt 1 — 2026-07-03T06:19:51Z

### Implementation Plan
- Confirm red: run `test_ac1_fact_written_to_db_with_embedding` and verify it fails with `assert 1 == 2`
- Apply the plan's exact fix in `_conflict_check`: precompute `max_distance = 1 - threshold` in Python and bind `$2` directly to that float, removing the `(1 - $2)` in-SQL arithmetic that let Postgres infer an integer type for the parameter
- Run `just lint`, `just test-unit`, `just type-check`
- Run the three named integration tests; since RC2 (event-loop) and RC3 (codec) fixes are owned by parallel tasks, also write a standalone isolated script hitting the real Ollama+Postgres stack directly through `_conflict_check` to get an unambiguous pass/fail on the threshold logic itself
- Clean up the standalone script (not part of the deliverable) and commit only the production fix

### Files Changed
- modified `apps/backend/src/second_brain/nodes/memory_persistence.py` — `_conflict_check`: bind precomputed `max_distance` directly instead of doing `1 - $2` in SQL

### New Tests
(none — this task fixes production code; the failing tests already existed in `test_memory_system.py` per the spec/plan)

### Key Decisions
- Verified the fix in isolation via a standalone `asyncio.run()` script that calls `_conflict_check` directly against the real Ollama+Postgres stack (same `get_pgvector_pool()` asyncpg pool used in production), because the full `test_memory_system.py` suite also depends on RC2 (event-loop) and RC3 (codec) fixes owned by concurrent sibling tasks. This isolated the conflict-detection logic from those unrelated, in-flight failures. Confirmed AC-1 ("vegetarian" vs "hiking", similarity 0.60) → no conflict, and AC-2 ("Berlin" vs "Berlin now", similarity 0.9697) → conflict detected. Script was deleted after verification; not committed.
- Confirmed `test_ac1_fact_written_to_db_with_embedding` now progresses past the `len(rows) == 2` assertion (previously failed there with `assert 1 == 2`) and instead fails later on `len(row.embedding) == 1024` — an RC3 codec/string-vs-list issue owned by task-2, not a regression from this fix.
- Confirmed `test_ac2_conflict_detected_not_written` now fails with `RuntimeError: Event loop is closed` (RC2, owned by task-1), not with any threshold-truncation symptom.

### Lint Output
PASS

### Test Output
PASS (just test-unit: 209 passed, 0 new — pre-existing suite; no regressions)
Integration test_memory_system.py: threshold-truncation symptom (`assert 1 == 2`) eliminated; remaining failures in that file are RC2/RC3, owned by parallel tasks per task instructions. Standalone isolated verification against real Ollama+Postgres stack: AC-1 PASS, AC-2 PASS.

### Type Check Output
0 errors, 0 warnings, 8 notes (all 8 notes pre-existing `reportUnknownArgumentType` info-level notes on asyncpg `Record`/pgvector-related code, unrelated to this change)

### Commit
`e16507c`

### Outcome: success
