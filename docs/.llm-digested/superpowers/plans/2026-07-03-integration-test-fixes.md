# Fix `just test-integration` Implementation Plan

Source: docs/superpowers/plans/2026-07-03-integration-test-fixes.md
Primary-Topic: integration-test-fixes
Secondary-Topics: memory-persistence, database-migrations

## Key Concepts

- Goal: make all 20 tests in `just test-integration` pass by fixing 4 independent root causes discovered by root-causing failures against the live Postgres + Ollama stack.
- Architecture: no architectural change — three surgical fixes: one production SQL bug (untyped bind parameter), two test-infrastructure fixes (event-loop scope, pgvector codec registration), and one stale-test correction (assertion inverted to match an already-shipped schema migration).
- Tech stack involved: pytest / pytest-asyncio 1.4.0, asyncpg, pgvector, SQLAlchemy, psycopg2.
- Global constraints: `just format`, `just lint`, `just type-check`, `just test-unit` must all pass with no errors after every task. No new dependencies — `pgvector.psycopg2` ships with the already-installed `pgvector` package. Tests require the live Docker stack (`just up-all` — Postgres `app_postgres` and Ollama must be running).
- Related docs: full root-cause detail in `docs/bugs/003-integration-test-failures.md`; full spec/ACs in `docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md`.
- File map: modifies `apps/backend/tests/integration/test_memory_system.py`, `apps/backend/tests/integration/test_query_graph.py`, `apps/backend/src/second_brain/nodes/memory_persistence.py`, `apps/backend/tests/integration/test_migration.py`.

### Task 1 — Session-scoped event loop for real-DB integration tests (RC2)

- Root cause: `embeddings.py`'s `_client` (module-level `httpx.AsyncClient`) and `db/pool.py`'s `_pgvector_pool`/`_pgvector_pool_lock` are process-lifetime singletons. pytest-asyncio's default gives each test function a new event loop; once that loop closes, the next test reusing a cached connection crashes with `RuntimeError: Event loop is closed` or an asyncpg `InterfaceError`.
- Fix in `test_memory_system.py`: change module-level `pytestmark = pytest.mark.integration` to `pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]`, and remove the now-redundant per-test `@pytest.mark.asyncio` decorators on `test_ac1_fact_written_to_db_with_embedding`, `test_ac2_conflict_detected_not_written`, `test_ac4_correction_written_with_embedding`, and `test_full_memory_loop_persist_then_retrieve`.
- Fix in `test_query_graph.py`: add `@pytest.mark.asyncio(loop_scope="session")` to `test_ac5_pii_redacted_before_llm_sees_message` and `test_ac6_pii_redacted_in_final_answer` only. `test_ac10_null_session_id_creates_new_thread_uuid_continues` stubs out `memory_retrieval_node` and never touches the real singletons, so it stays untouched.
- Verification: before the fix, `test_ac2_conflict_detected_not_written` and `test_full_memory_loop_persist_then_retrieve` fail with event-loop/InterfaceError. After the fix, those errors are gone (remaining failures are the RC1/RC3 assertion failures, fixed in later tasks).
- Commit message: `fix(test): share one event loop across real-DB integration tests`.

### Task 2 — Register pgvector codec on the raw-SQL test fixture (RC3)

- Root cause: `db_engine` fixture is a plain `create_engine(sync_url)` using psycopg2, which has no adapter for Postgres's custom `vector` type — raw `text()` queries return the pgvector text literal (a string) instead of a parsed `list[float]`.
- Fix: in `test_memory_system.py`, import `register_vector` from `pgvector.psycopg2` and `event` from `sqlalchemy`; in the `db_engine` fixture, after creating the engine, register the codec via `event.listens_for(engine, "connect")(lambda dbapi_conn, _: register_vector(dbapi_conn))` before yielding.
- Rationale comment: SQLModel's ORM path gets the vector codec for free from `pgvector.sqlalchemy.Vector`, but this fixture reads back rows outside the ORM, so it needs the codec registered explicitly.
- Verification: before fix, `test_ac4_correction_written_with_embedding` fails with `AssertionError: assert 12764 == 1024` (embedding column read back as a string). After fix: PASS.
- Commit message: `fix(test): register pgvector codec on raw-SQL test fixture`.

### Task 3 — Fix the conflict-check threshold type coercion (RC1)

- Root cause (production bug): in `apps/backend/src/second_brain/nodes/memory_persistence.py`, `_conflict_check`'s SQL computed `(1 - $2)` where `$2` is the threshold parameter's only occurrence. Postgres infers `$2`'s type from the untyped literal `1` (→ integer), so asyncpg truncates the real threshold (`0.95`) to `0`, making the WHERE clause effectively `distance < 1` — nearly any two facts appear to "conflict".
- Fix: precompute `max_distance = 1 - threshold` in Python and bind it directly as `$2`, changing the SQL WHERE clause from `(embedding<=>$1) < (1 - $2)` to `(embedding<=>$1) < $2`.
- Verified real-embedding behavior after fix: "vegetarian" vs "hiking" (similarity 0.60) → no conflict; "Berlin" vs "Berlin now" (similarity 0.97) → conflict.
- Verification: before fix, `test_ac1_fact_written_to_db_with_embedding` fails with `AssertionError: assert 1 == 2` (second fact wrongly treated as conflicting). After fix: `test_ac1...`, `test_ac2_conflict_detected_not_written`, and `test_full_memory_loop_persist_then_retrieve` all pass — `test_ac2` passing proves the fix didn't just disable the check (a real conflict is still caught). `just type-check` must show no errors/warnings (signature/return type unchanged).
- Commit message: `fix(memory): bind precomputed max-distance in conflict-check SQL` (body explains the untyped-literal type-inference bug).

### Task 4 — Flip the stale FK tests to match the shipped migration (RC4)

- Root cause: migration `002_drop_source_session_fk.py` (shipped in commit `d9bbc69`) deliberately dropped the FK from `learned_facts`/`model_corrections` to `chat_history` because "chat_history is never written by the application." The two integration tests in `apps/backend/tests/integration/test_migration.py` (lines ~121-132) were never updated to match and still assert the FK exists.
- Fix: rename and flip the assertions — `test_learned_facts_fk_to_chat_history` → `test_learned_facts_no_fk_to_chat_history` (assert `"chat_history" not in referred`), and `test_model_corrections_fk_to_chat_history` → `test_model_corrections_no_fk_to_chat_history` (same assertion flip). Both get a docstring noting migration 002 dropped the FK.
- Verification: before fix, both tests fail (`"chat_history" in referred` is false). After fix: all tests in `test_migration.py` pass.
- Commit message: `fix(test): assert learned_facts/model_corrections have no FK to chat_history` (body notes migration 002 / commit `d9bbc69` and that the old tests asserted the reversed, pre-migration design).

### Task 5 — Full verification

- Run `just test-integration` twice in a row, expect `20 passed` both times (rules out residual event-loop flakiness from Task 1).
- Run full Done-Means checklist: `just format && just lint && just type-check && just test-unit` — all must pass with no errors/warnings.
- Confirm no other tests regressed: `just test-integration -v 2>&1 | tail -30` should show `20 passed`, 0 failed, 0 skipped-unexpectedly.

### Done Checklist

- `just format` passes
- `just lint` passes
- `just type-check` passes
- `just test-unit` passes
- `just test-integration` passes (20/20), twice in a row
- `docs/bugs/003-integration-test-failures.md` and this plan committed alongside the fixes
