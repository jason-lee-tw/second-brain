# Integration Testing

`just test-integration` runs 20 tests against the live Postgres+Ollama stack; a 2026-07-03 investigation found 8 failing from four independent root causes and shipped one production fix plus three test-infrastructure/test-correctness fixes.

## Key Concepts

- `just test-integration` exercises the real stack (Postgres `app_postgres` + Ollama), unlike unit tests — it is the merge gate that proves DB/embedding/async behavior actually works, not just that it's mocked correctly.
- On 2026-07-03, 8 of 20 tests failed: `test_memory_system.py::test_ac1_fact_written_to_db_with_embedding`, `test_ac2_conflict_detected_not_written`, `test_ac4_correction_written_with_embedding`, `test_full_memory_loop_persist_then_retrieve`; `test_migration.py::test_learned_facts_fk_to_chat_history`, `test_model_corrections_fk_to_chat_history`; `test_query_graph.py::test_ac5_pii_redacted_before_llm_sees_message`, `test_ac6_pii_redacted_in_final_answer`. Severity P1: the suite could not be trusted as a merge gate.
- Five-why root-cause analysis traced the 8 failures to **4 independent, unrelated causes** — not one shared bug. This is a recurring institutional lesson: a batch of red tests can have multiple disjoint root causes, and each needs its own fix rather than one blanket patch.
- All 4 root causes predate the Python 3.12→3.13 upgrade (commit `948518b`) — the upgrade didn't cause them, it just surfaced them by forcing a fresh integration run. See [[python-3-13-upgrade]].
- `test_ingestion_graph.py` passed cleanly throughout because it mocks `embed_text` entirely and never exercises the real async singletons or SQL paths that the other three failing suites hit — flagged as a coverage gap for those other suites.
- The fix set is deliberately non-architectural: one production SQL bug, two test-infrastructure fixes, and one stale-test correction. Redesigning `embeddings.py`/`db/pool.py` away from module-level singletons was considered and explicitly rejected, since production is unaffected (uvicorn keeps one event loop alive for the whole process) — only pytest's per-test event-loop churn triggers the issue.
- Fix branch `fix/000-integration-test`, spec status Approved, dated 2026-07-03.

## Root Causes and Fixes

### RC1 — conflict-check threshold silently disabled (production bug)

- Location: `apps/backend/src/second_brain/nodes/memory_persistence.py`, `_conflict_check` (lines ~28-41).
- Cause: SQL did arithmetic on an untyped bind parameter — `WHERE (embedding<=>$1) < (1 - $2)`, with `$2` bound to `settings.memory_conflict_threshold` (0.95). Because `$2` only appears inside `1 - $2`, Postgres infers `$2`'s type from the untyped literal `1` (integer), so asyncpg truncates the real float `0.95` down to `0`. `(1 - $2)` then evaluates to `1`, so the WHERE clause matches almost everything.
- Effect: the conflict check has been silently disabled since commit `a704f72` — it flagged an unrelated fact ("The user loves hiking.") as conflicting with ("The user is a vegetarian."; real cosine similarity 0.5975, well under 0.95), so `_persist_fact` skipped the write and `test_ac1` only wrote 1 of 2 facts. Never caught before because `test_ac1` was never actually run to green.
- Fix: precompute `max_distance = 1 - threshold` in Python and bind it directly as `$2`; SQL changes to `WHERE (embedding<=>$1) < $2` — no arithmetic on the bind parameter inside SQL.
- Verified real-embedding behavior after the fix: "vegetarian" vs "hiking" (similarity 0.60) → no conflict (AC-1); "Berlin" vs "Berlin now" (similarity 0.97) → conflict (AC-2). `test_ac2` passing alongside `test_ac1` proves the fix didn't just disable the check outright.
- Lesson: never perform arithmetic on an untyped bind parameter inside raw SQL — Postgres/asyncpg can silently coerce/truncate the type.
- Commit message used: `fix(memory): bind precomputed max-distance in conflict-check SQL`.

### RC2 — async singletons don't survive pytest-asyncio's per-test event loop

- Symptoms: `RuntimeError: Event loop is closed` in `memory_retrieval_node`; `asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress` during `asyncpg/pool.py` release.
- Affected process-lifetime singletons: `embeddings.py`'s module-level `httpx.AsyncClient` (`_client`), and `db/pool.py`'s `_pgvector_pool` / `_pgvector_pool_lock`. See [[postgres-connection-pooling]].
- Cause: pytest-asyncio's default is a new event loop per test function; once that loop closes, a singleton connection/lock bound to it becomes unusable in the next test that reuses it.
- Why production is unaffected: uvicorn keeps exactly one event loop alive for the whole process, so singletons never outlive their loop there — this is test-only.
- Why `test_ingestion_graph.py` is immune: it mocks `embed_text` in every test and never touches the real singleton.
- Fix: give `test_memory_system.py` and `test_query_graph.py` a session-scoped event loop. In `test_memory_system.py`, module-level `pytestmark` becomes `[pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]`, with the now-redundant per-test `@pytest.mark.asyncio` decorators removed from `test_ac1`, `test_ac2`, `test_ac4`, and `test_full_memory_loop_persist_then_retrieve`. In `test_query_graph.py`, `@pytest.mark.asyncio(loop_scope="session")` is added only to `test_ac5_pii_redacted_before_llm_sees_message` and `test_ac6_pii_redacted_in_final_answer` — `test_ac10_null_session_id_creates_new_thread_uuid_continues` stubs `memory_retrieval_node` and never touches the real singletons, so it's untouched. See [[query-graph]] for the PII-redaction tests this affects.
- Commit message used: `fix(test): share one event loop across real-DB integration tests`.

### RC3 — raw-SQL test fixture can't decode the pgvector column

- Symptom: `AssertionError: assert 12764 == 1024` — the embedding came back as the pgvector text literal (a 12764-character string) instead of a parsed `list[float]` of dimensionality 1024.
- Cause: `test_memory_system.py`'s `db_engine` fixture is a plain `create_engine(sync_url)` using psycopg2 with no pgvector adapter registered, so raw `text()` SQL queries fall back to the raw text representation of the custom Postgres `vector` type. The ORM path (SQLModel + `pgvector.sqlalchemy.Vector`) decodes vectors automatically, but this fixture reads back rows outside the ORM. See [[pgvector-embeddings]] and [[database-schema]].
- Fix: import `register_vector` from `pgvector.psycopg2` and `event` from `sqlalchemy`; in the `db_engine` fixture, register the codec via `event.listens_for(engine, "connect")(lambda dbapi_conn, _: register_vector(dbapi_conn))` before yielding the engine.
- Commit message used: `fix(test): register pgvector codec on raw-SQL test fixture`.

### RC4 — stale test contradicts an intentional schema decision

- Symptom: `test_learned_facts_fk_to_chat_history` fails with `AssertionError: assert 'chat_history' in set()`.
- Cause: `learned_facts.source_session` (and `model_corrections.source_session`) have no foreign key to `chat_history` — migration `002_drop_source_session_fk.py` (commit `d9bbc69`, "chat_history not written by app") deliberately dropped it, since LangGraph uses its own checkpoint tables and `chat_history` is never written by the application. `test_migration.py` (lines ~121-132) hadn't been touched since the very first commit and still asserted the FK's presence — no integration run had closed the loop between the schema fix and the test suite until this investigation. See [[database-schema]].
- Fix: rename and flip both assertions — `test_learned_facts_fk_to_chat_history` → `test_learned_facts_no_fk_to_chat_history` (assert `"chat_history" not in referred`), and likewise for `test_model_corrections_fk_to_chat_history` → `test_model_corrections_no_fk_to_chat_history` — each with a docstring noting migration 002 as the source of truth (AC-5).
- Commit message used: `fix(test): assert learned_facts/model_corrections have no FK to chat_history`.

## Verification

- Acceptance criteria (AC-1 through AC-5): correct conflict/no-conflict behavior on real embeddings, `just test-integration` passing 20/20 twice in a row (rules out residual event-loop flakiness from the RC2 fix), `just format`/`just lint`/`just type-check`/`just test-unit` all clean, and the renamed FK tests asserting absence.
- Fix scope: 3 files touched — 1 production file (`apps/backend/src/second_brain/nodes/memory_persistence.py`) and 2 test files (`apps/backend/tests/integration/test_memory_system.py` + `test_query_graph.py`, and `apps/backend/tests/integration/test_migration.py`). No schema changes beyond what migration 002 already applied, no new dependencies (`pgvector.psycopg2` ships with the already-installed `pgvector` package).
- Explicitly out of scope: redesigning the singleton architecture in `embeddings.py`/`db/pool.py`, the RAGAS evaluation harness, and any behavior change to conflict-resolution UX beyond the threshold-comparison fix itself.

## Open Questions

- **memory_conflict_threshold default**: this page (RC1 section) states the value bound in the conflict-check bug was `0.95`, but [[memory-system]], [[query-workflow]], and [[second-brain-architecture]] state the default is `0.85`. Unresolved — needs source verification.

## Sources

- Bugs Index — `docs/bugs/000-index.md`
- Bug: `just test-integration` — 8/20 tests failing — `docs/bugs/003-integration-test-failures.md`
- Fix `just test-integration` Implementation Plan — `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`
- Spec: Fix `just test-integration` failures (4 independent root causes) — `docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md`

## Related Topics

- [[known-issues]]
- [[database-schema]]
- [[memory-system]]
- [[postgres-connection-pooling]]
- [[pgvector-embeddings]]
- [[python-3-13-upgrade]]
- [[query-graph]]
- [[database-access-patterns]]
