# Fix `just test-integration` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 20 tests in `just test-integration` pass, fixing 4 independent root causes found by root-causing against the live Postgres+Ollama stack.

**Architecture:** No architectural change. Three surgical fixes: one production SQL bug (untyped bind parameter), two test-infrastructure fixes (event-loop scope, pgvector codec registration), and one stale-test correction (assertion inverted to match an already-shipped schema migration).

**Tech Stack:** pytest / pytest-asyncio 1.4.0, asyncpg, pgvector, SQLAlchemy, psycopg2.

## Global Constraints

- `just format`, `just lint`, `just type-check`, `just test-unit` must all pass with no errors after every task (per CLAUDE.md "Done Means").
- No new dependencies — `pgvector.psycopg2` ships with the already-installed `pgvector` package (verified: `python -c "import pgvector.psycopg2"` succeeds in the venv).
- Tests require the live Docker stack (`just up-all`) — Postgres (`app_postgres`) and Ollama must be running for every verification step below.
- Full root-cause detail for each task: `docs/bugs/003-integration-test-failures.md`. Full spec/ACs: `docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md`.

---

## File Map

| Action | Path                                                        | Change                                                                                      |
| ------ | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Modify | `apps/backend/tests/integration/test_memory_system.py`      | Session-scoped asyncio loop marker; `db_engine` fixture registers pgvector codec            |
| Modify | `apps/backend/tests/integration/test_query_graph.py`        | Session-scoped asyncio loop marker on `test_ac5`/`test_ac6`                                 |
| Modify | `apps/backend/src/second_brain/nodes/memory_persistence.py` | `_conflict_check` binds precomputed max-distance instead of doing arithmetic on `$2` in SQL |
| Modify | `apps/backend/tests/integration/test_migration.py`          | Flip + rename the two FK tests to assert absence                                            |

---

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

---

## Task 2: Register pgvector codec on the raw-SQL test fixture (RC3)

**Files:**

- Modify: `apps/backend/tests/integration/test_memory_system.py:1-36` (imports + `db_engine` fixture)

**Context:** `db_engine` is a plain `create_engine(sync_url)` (psycopg2). psycopg2 has no adapter for Postgres's custom `vector` type, so raw `text()` queries return the pgvector text literal (a string) instead of a parsed `list[float]`. Full detail: `docs/bugs/003-integration-test-failures.md` Root Cause 3.

- [ ] **Step 1: Confirm the failure (red)**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py::test_ac4_correction_written_with_embedding -v
```

Expected: FAIL with `AssertionError: assert 12764 == 1024` (the embedding
column is a string, not a list).

- [ ] **Step 2: Register the codec in the fixture**

Edit `apps/backend/tests/integration/test_memory_system.py`:

```python
# BEFORE
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

# AFTER
import os
import uuid

import pytest
from pgvector.psycopg2 import register_vector
from sqlalchemy import create_engine, event, text
```

```python
# BEFORE
@pytest.fixture(scope="module")
def db_engine():
    """Connect to the real Postgres. Skip if DATABASE_URL is a test placeholder."""
    url = _DATABASE_URL
    if "test-api-key" in url or ("localhost" not in url and "app_postgres" not in url):
        pytest.skip(
            "DATABASE_URL does not point to a real running database"
            " — skipping memory system integration test"
        )
    # Strip asyncpg driver suffix — sync SQLAlchemy doesn't support it
    sync_url = url.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    yield engine
    engine.dispose()

# AFTER
@pytest.fixture(scope="module")
def db_engine():
    """Connect to the real Postgres. Skip if DATABASE_URL is a test placeholder."""
    url = _DATABASE_URL
    if "test-api-key" in url or ("localhost" not in url and "app_postgres" not in url):
        pytest.skip(
            "DATABASE_URL does not point to a real running database"
            " — skipping memory system integration test"
        )
    # Strip asyncpg driver suffix — sync SQLAlchemy doesn't support it
    sync_url = url.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    # Raw text() queries need the vector codec registered explicitly —
    # SQLModel's ORM path gets it for free from pgvector.sqlalchemy.Vector,
    # but this fixture reads back rows outside the ORM.
    event.listens_for(engine, "connect")(
        lambda dbapi_conn, _: register_vector(dbapi_conn)
    )
    yield engine
    engine.dispose()
```

- [ ] **Step 3: Confirm the fix**

```bash
uv run --package second-brain pytest apps/backend/tests/integration/test_memory_system.py::test_ac4_correction_written_with_embedding -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/test_memory_system.py
git commit -m "fix(test): register pgvector codec on raw-SQL test fixture"
```

---

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

---

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

---

## Task 5: Full verification

- [ ] **Step 1: Run the full integration suite twice in a row**

```bash
just test-integration
just test-integration
```

Expected: `20 passed` both times (rules out any residual event-loop
flakiness from Task 1).

- [ ] **Step 2: Run the full Done-Means checklist**

```bash
just format && just lint && just type-check && just test-unit
```

Expected: all pass with no errors or warnings.

- [ ] **Step 3: Confirm no other tests regressed**

```bash
just test-integration -v 2>&1 | tail -30
```

Expected: `20 passed`, 0 failed, 0 skipped-unexpectedly.

---

## Done Checklist

- [ ] `just format` passes
- [ ] `just lint` passes
- [ ] `just type-check` passes
- [ ] `just test-unit` passes
- [ ] `just test-integration` passes (20/20), twice in a row
- [ ] `docs/bugs/003-integration-test-failures.md` and this plan committed alongside the fixes
