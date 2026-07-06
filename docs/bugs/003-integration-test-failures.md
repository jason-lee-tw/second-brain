# Bug: `just test-integration` — 8/20 tests failing

**Date:** 2026-07-03
**Branch:** fix/000-integration-test
**Severity:** P1 — integration suite cannot be trusted as a merge gate

---

## Symptom

```
FAILED apps/backend/tests/integration/test_memory_system.py::test_ac1_fact_written_to_db_with_embedding
FAILED apps/backend/tests/integration/test_memory_system.py::test_ac2_conflict_detected_not_written
FAILED apps/backend/tests/integration/test_memory_system.py::test_ac4_correction_written_with_embedding
FAILED apps/backend/tests/integration/test_memory_system.py::test_full_memory_loop_persist_then_retrieve
FAILED apps/backend/tests/integration/test_migration.py::test_learned_facts_fk_to_chat_history
FAILED apps/backend/tests/integration/test_migration.py::test_model_corrections_fk_to_chat_history
FAILED apps/backend/tests/integration/test_query_graph.py::test_ac5_pii_redacted_before_llm_sees_message
FAILED apps/backend/tests/integration/test_query_graph.py::test_ac6_pii_redacted_in_final_answer
=================== 8 failed, 12 passed, 1 warning in 3.51s ====================
```

Four independent root causes, all predating the Python 3.12→3.13 upgrade
(`948518b`). `test_ingestion_graph.py` passes cleanly because it mocks
`embed_text` entirely and never exercises the buggy code paths below.

---

## Root Cause 1 — conflict-check threshold silently disabled

### Reproduction

```python
# apps/backend/src/second_brain/nodes/memory_persistence.py:28-41
async def _conflict_check(embedding: list[float]) -> list[dict[str, Any]]:
    threshold = settings.memory_conflict_threshold  # 0.95
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, fact, 1-(embedding<=>$1) AS score"
            " FROM learned_facts"
            " WHERE (embedding<=>$1) < (1 - $2)"
            " ORDER BY embedding<=>$1 ASC LIMIT 5",
            embedding, threshold,
        )
        return [dict(r) for r in rows]
```

Direct query against the live DB with the exact same parameters:

```sql
SELECT (embedding<=>$1) AS dist, (1-$2) AS rhs, (embedding<=>$1) < (1-$2) AS matched
FROM learned_facts;
-- e=embed("The user loves hiking."), $2=0.95
--> dist=0.4024727646220867, rhs=1, matched=true
```

Real cosine similarity between "The user is a vegetarian." and "The user
loves hiking." is 0.5975 (well under the 0.95 threshold) — yet the query
flags it as a conflict.

### Five-Why Root Cause

| Why                                          | Finding                                                                                                                                                                                                                                    |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Why does `test_ac1` only write 1 of 2 facts? | `_persist_fact` treats the 2nd fact as conflicting with the 1st and skips the write                                                                                                                                                        |
| Why does an unrelated fact "conflict"?       | `_conflict_check`'s WHERE clause `(embedding<=>$1) < (1 - $2)` evaluates to `< 1`, not `< 0.05`                                                                                                                                            |
| Why does `(1 - $2)` evaluate to `1`?         | `$2` is bound as integer `0`, not float `0.95` — confirmed via direct query returning `rhs=1`                                                                                                                                              |
| Why is `$2` bound as integer `0`?            | `$2` only appears inside `1 - $2`; with no other type context, Postgres infers `$2`'s type from the untyped integer literal `1`, i.e. `integer`. asyncpg then encodes the Python float `0.95` into an integer parameter, truncating to `0` |
| Why wasn't this caught earlier?              | The integration test that would catch it (`test_ac1`) was never actually run to green — this is the first `just test-integration` run to be root-caused end-to-end                                                                         |

### Root Cause

`memory_persistence.py:36` performs arithmetic on an untyped bind parameter
inside SQL (`1 - $2`), letting Postgres/asyncpg silently coerce the
threshold to an integer and truncate it to 0. The conflict check has been
effectively disabled since it was written (`a704f72`).

### Fix

Compute the max-distance cutoff in Python and bind it directly — no
arithmetic on the parameter inside SQL:

```python
max_distance = 1 - threshold
...
"WHERE (embedding<=>$1) < $2"
...
embedding, max_distance,
```

See fix plan: `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`

---

## Root Cause 2 — async singletons don't survive pytest-asyncio's per-test event loop

### Reproduction

```
E   RuntimeError: Event loop is closed
    .../asyncio/base_events.py:833: in call_soon
    self._check_closed()
    During task with name 'memory_retrieval_node'
```

```
E   asyncpg.exceptions._base.InterfaceError: cannot perform operation: another operation is in progress
    .../asyncpg/pool.py:239: in release
```

### Five-Why Root Cause

| Why                                                                               | Finding                                                                                                                                                                                            |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Why does the 2nd/4th async DB test in a module crash with "Event loop is closed"? | It reuses an httpx connection or asyncpg pool connection that was opened under a _previous_ test's event loop                                                                                      |
| Why does a previous test's event loop matter?                                     | `embeddings.py:5` (`_client = httpx.AsyncClient(...)`) and `db/pool.py:14-15` (`_pgvector_pool`, `_pgvector_pool_lock`) are module-level singletons, created once and cached for the whole process |
| Why does that break under pytest?                                                 | pytest-asyncio's default is a **new event loop per test function**; once that loop closes, any connection/lock bound to it is unusable                                                             |
| Why doesn't `test_ingestion_graph.py` see this?                                   | It patches `embed_text` with an `AsyncMock` in every test — the real singleton is never touched                                                                                                    |
| Why doesn't this happen in production?                                            | uvicorn keeps exactly one event loop alive for the entire process lifetime, so the singletons never outlive their loop there                                                                       |

### Root Cause

Test-only: `test_memory_system.py` and `test_query_graph.py` exercise the
real `embed_text` / `get_pgvector_pool` singletons, and pytest-asyncio's
function-scoped event loop tears down and recreates the loop between tests
in the same module, poisoning the cached httpx/asyncpg connections.

### Fix

Give these two files a session-scoped event loop via pytest-asyncio's
`loop_scope="session"` marker, so the singletons are created once and never
observe a closed loop — mirroring the single-event-loop-per-process
lifetime that already holds in production.

See fix plan: `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`

---

## Root Cause 3 — raw-SQL test fixture can't decode the pgvector column

### Reproduction

```
E   AssertionError: assert 12764 == 1024
E    +  where 12764 = len('[-0.00730595,-0.015381461,...]')
```

`test_memory_system.py`'s `db_engine` fixture is a plain
`create_engine(sync_url)` (psycopg2, no pgvector registration). Querying the
`embedding` column via raw `text()` SQL returns the pgvector text literal
(a string), not a parsed list — `len()` measures string length (12764
characters), not vector dimensionality (1024).

### Five-Why Root Cause

| Why                                             | Finding                                                                                                                                                                                                  |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Why does `len(rows[0].embedding) == 1024` fail? | `rows[0].embedding` is a `str`, not a `list[float]`                                                                                                                                                      |
| Why is it a string?                             | psycopg2 has no adapter registered for Postgres's custom `vector` type on this engine, so it falls back to returning the raw text representation                                                         |
| Why is no adapter registered?                   | The ORM path (`SQLModel` + `pgvector.sqlalchemy.Vector` column type in `db/models.py`) decodes it automatically, but this fixture bypasses the ORM and queries with `text()` on a bare `create_engine()` |
| Why does the fixture bypass the ORM?            | It needs to read back rows across the SQLModel session boundary to verify what `memory_persistence_node` wrote, so it opens its own connection                                                           |

### Root Cause

`db_engine` fixture never registers `pgvector.psycopg2.register_vector` on
its connections, so raw-SQL reads of `vector` columns return strings.

### Fix

Register the codec on every connection from that engine via SQLAlchemy's
`connect` event hook.

See fix plan: `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`

---

## Root Cause 4 — stale test contradicts an intentional later schema decision

### Reproduction

```python
def test_learned_facts_fk_to_chat_history(db_engine):
    ...
    assert "chat_history" in referred
# AssertionError: assert 'chat_history' in set()
```

### Five-Why Root Cause

| Why                                            | Finding                                                                                                                                                                                                                    |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Why does the FK assertion fail?                | `learned_facts.source_session` has no foreign key to `chat_history`                                                                                                                                                        |
| Why is there no FK?                            | Migration `002_drop_source_session_fk.py` explicitly drops it                                                                                                                                                              |
| Why was it dropped?                            | Commit `d9bbc69` ("fix(db): drop source_session FK — chat_history not written by app"): `chat_history` is never written by the application — LangGraph uses its own checkpoint tables — so the FK could never be satisfied |
| Why does the test still expect the FK?         | `test_migration.py` hasn't been touched since the very first commit (`af430a2`), predating `d9bbc69`                                                                                                                       |
| Why wasn't it caught at the time of `d9bbc69`? | No integration test run closed the loop between the schema fix and the test suite until now                                                                                                                                |

### Root Cause

`test_migration.py::test_learned_facts_fk_to_chat_history` and
`test_model_corrections_fk_to_chat_history` assert a design that was
deliberately reversed; the tests were never updated to match.

### Fix

Flip both assertions to confirm the FK's absence (regression guard against
accidental reintroduction), and rename/redocument to reference migration 002.

See fix plan: `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`
