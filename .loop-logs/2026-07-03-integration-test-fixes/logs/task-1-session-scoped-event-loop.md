# Task 1 Log: Session-scoped event loop for real-DB integration tests (RC2)

## Task Context

### Plan Section
## Task 1: Session-scoped event loop for real-DB integration tests (RC2)

**Files:**

- Modify: `apps/backend/tests/integration/test_memory_system.py:18` (module-level `pytestmark`), lines `77`, `115`, `170`, `204` (drop redundant per-test `@pytest.mark.asyncio`)
- Modify: `apps/backend/tests/integration/test_query_graph.py:75`, `145` (add loop_scope marker to `test_ac5`/`test_ac6` only — `test_ac10` at line 209 stubs out `memory_retrieval_node` and never touches the real singletons, so it must stay untouched)

**Context:** `embeddings.py`'s `_client` (module-level `httpx.AsyncClient`) and `db/pool.py`'s `_pgvector_pool`/`_pgvector_pool_lock` are process-lifetime singletons. pytest-asyncio's default gives each test function a _new_ event loop; once that loop closes, the next test to reuse a cached connection crashes with `RuntimeError: Event loop is closed` or `asyncpg...InterfaceError: another operation is in progress`. Full detail: `docs/bugs/003-integration-test-failures.md` Root Cause 2.

- [ ] **Step 1: Confirm the current flakiness (red)**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py -v
```

Expected: `test_ac2_conflict_detected_not_written` and
`test_full_memory_loop_persist_then_retrieve` FAIL with `RuntimeError: Event
loop is closed` (or an asyncpg `InterfaceError`), alternating with the
assertion failures from RC1/RC3 (fixed in later tasks — ignore those for
now).

- [ ] **Step 2: Give `test_memory_system.py` a session-scoped loop**

Edit `apps/backend/tests/integration/test_memory_system.py`:

```python
# BEFORE (line 18)
pytestmark = pytest.mark.integration

# AFTER
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
```

Remove the now-redundant per-test decorators (the module-level `pytestmark`
already covers every test in the file):

```python
# BEFORE (lines 77-78, 115-116, 170-171, 204-205)
@pytest.mark.asyncio
async def test_ac1_fact_written_to_db_with_embedding(db_engine):

# AFTER
async def test_ac1_fact_written_to_db_with_embedding(db_engine):
```

Apply the same removal to `test_ac2_conflict_detected_not_written`,
`test_ac4_correction_written_with_embedding`, and
`test_full_memory_loop_persist_then_retrieve`.

- [ ] **Step 3: Give `test_query_graph.py`'s ac5/ac6 a session-scoped loop**

Edit `apps/backend/tests/integration/test_query_graph.py`:

```python
# BEFORE (line 75-76)
@pytest.mark.integration
async def test_ac5_pii_redacted_before_llm_sees_message():

# AFTER
@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_ac5_pii_redacted_before_llm_sees_message():
```

```python
# BEFORE (line 145-146)
@pytest.mark.integration
async def test_ac6_pii_redacted_in_final_answer():

# AFTER
@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_ac6_pii_redacted_in_final_answer():
```

Leave `test_ac10_null_session_id_creates_new_thread_uuid_continues` (line 209) untouched — it stubs `memory_retrieval_node` and never touches the real
`embed_text`/`get_pgvector_pool` singletons, so it isn't affected by this bug
and doesn't need the marker.

- [ ] **Step 4: Confirm the event-loop errors are gone**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py apps/backend/tests/integration/test_query_graph.py -v
```

Expected: no more `RuntimeError: Event loop is closed` or
`asyncpg...InterfaceError` anywhere in the output. Remaining failures should
only be the RC1/RC3 assertion failures (`assert 1 == 2`,
`assert 12764 == 1024`) — those are fixed in Tasks 2-3.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/tests/integration/test_memory_system.py apps/backend/tests/integration/test_query_graph.py
git commit -m "fix(test): share one event loop across real-DB integration tests"
```

### Acceptance Criteria
- AC-1: `pytestmark` in `test_memory_system.py` is `[pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]`, and the redundant per-test `@pytest.mark.asyncio` decorators on `test_ac1_fact_written_to_db_with_embedding`, `test_ac2_conflict_detected_not_written`, `test_ac4_correction_written_with_embedding`, and `test_full_memory_loop_persist_then_retrieve` are removed.
- AC-2: `test_ac5_pii_redacted_before_llm_sees_message` and `test_ac6_pii_redacted_in_final_answer` in `test_query_graph.py` each have `@pytest.mark.asyncio(loop_scope="session")` directly under `@pytest.mark.integration`; `test_ac10_null_session_id_creates_new_thread_uuid_continues` is left untouched.
- AC-3: Running `test_memory_system.py` and `test_query_graph.py` against the live stack produces no `RuntimeError: Event loop is closed` or asyncpg `InterfaceError` anywhere in the output (residual RC1/RC3 assertion failures owned by other tasks are acceptable).
- AC-4: `just lint` and `just test-unit` pass with no errors.

---

## Attempt 1 — 2026-07-03T06:20:48Z

### Implementation Plan
- Confirm current flakiness (red) by running `test_memory_system.py` against the live Docker stack
- Change `test_memory_system.py`'s module-level `pytestmark` to include `pytest.mark.asyncio(loop_scope="session")`, and remove the four now-redundant per-test `@pytest.mark.asyncio` decorators
- Add `@pytest.mark.asyncio(loop_scope="session")` under `@pytest.mark.integration` on `test_ac5_pii_redacted_before_llm_sees_message` and `test_ac6_pii_redacted_in_final_answer` in `test_query_graph.py` only, leaving `test_ac10` untouched
- Re-run both files to confirm the event-loop errors are gone
- Run `just lint` and `just test-unit` as hard gates

### Files Changed
- modified `apps/backend/tests/integration/test_memory_system.py` — session-scoped asyncio loop marker on `pytestmark`; removed 4 redundant per-test `@pytest.mark.asyncio` decorators
- modified `apps/backend/tests/integration/test_query_graph.py` — added `@pytest.mark.asyncio(loop_scope="session")` to `test_ac5_pii_redacted_before_llm_sees_message` and `test_ac6_pii_redacted_in_final_answer`

### New Tests
(none — test-infrastructure-only change; no new production code or tests, per task instructions)

### Key Decisions
- Confirmed the live Docker stack (`app_postgres`, backend, phoenix) was already up via `docker compose ps`; ran `uv sync --all-extras` inside the fresh worktree venv first since pytest wasn't yet installed there.
- **Red confirmation (before fix):** `uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py -v` → 4 failed: `test_ac1` and `test_ac4` failed with the expected RC1/RC3 assertion errors (`assert 1 == 2` type mismatch was actually `awaiting_conflict_clarification` mismatch for ac1 — see raw output below; `assert 12764 == 1024` for ac4); `test_ac2_conflict_detected_not_written` and `test_full_memory_loop_persist_then_retrieve` failed with `RuntimeError: Event loop is closed` — exactly matching the plan's predicted red state.
- **Green confirmation (after fix):** re-ran `test_memory_system.py` + `test_query_graph.py` together → 3 passed (`test_ac2`, `test_full_memory_loop_persist_then_retrieve`, `test_ac10`), 4 failed, **zero** `RuntimeError: Event loop is closed` / asyncpg `InterfaceError` occurrences anywhere in the output. The `test_ac1`/`test_ac4` failures are the expected residual RC1/RC3 assertion failures owned by Tasks 2/3 (untouched here, as instructed).
- **New finding (flagging, not fixing):** `test_ac5_pii_redacted_before_llm_sees_message` and `test_ac6_pii_redacted_in_final_answer` now fail with `anthropic.AuthenticationError: 401 invalid x-api-key` from a real (unmocked) call to `memory_agent_node`'s `_llm` (`ChatAnthropic`), which always runs unconditionally after synthesis in the query graph. This is **not** RC1/RC2/RC3/RC4 — it's a previously-masked test gap: before the RC2 fix, `memory_retrieval_node` crashed with `RuntimeError: Event loop is closed` *before* the graph ever reached `memory_agent_node`, hiding the fact that ac5/ac6 (unlike ac10) never mock `second_brain.nodes.memory_agent._llm`. Reproduced this failure in isolation (`pytest test_query_graph.py -v` alone, no `test_memory_system.py` in the run) — same `AuthenticationError`, confirming it is unrelated to loop-scope sharing across files and is a standalone latent gap in `test_ac5`/`test_ac6`'s mocking. This is out of Task 1's file-map scope (fixing it would mean adding new mock patches beyond the two documented decorator edits) and isn't owned by Tasks 2/3/4 either — flagging here for the orchestrator/Task-5 full-verification step, since `just test-integration` will not reach 20/20 until `memory_agent._llm` is also mocked in these two tests.
- Task 1's own acceptance bar (per its instructions: event-loop-specific errors confirmed gone; lint + test-unit hard gates green) is met — proceeding to mark this task complete without touching the newly discovered ac5/ac6 mocking gap, per explicit instruction to not fix issues outside this task's scope.

### Lint Output
PASS (`just lint` → "All checks passed!")

### Test Output
PASS (`just test-unit` → 209 passed, 2 warnings)

Integration (best-effort, not a hard gate): `test_memory_system.py` + `test_query_graph.py` → 3 passed, 4 failed; **zero** event-loop errors (down from 2 `RuntimeError: Event loop is closed` failures pre-fix). Residual failures: `test_ac1`/`test_ac4` (RC1/RC3, owned by Tasks 2/3 — expected), `test_ac5`/`test_ac6` (newly-exposed unmocked-LLM gap — flagged above, not owned by any task in this plan).

### Commit
`33f90f1`

### Outcome: success
