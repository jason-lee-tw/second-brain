# Task 2 Log: Register pgvector codec on the raw-SQL test fixture (RC3)

## Task Context

### Plan Section
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

### Informal Criteria (Expected Outcomes)
- Step 1: `test_ac4_correction_written_with_embedding` FAILS with `AssertionError: assert 12764 == 1024`
- Step 3: same test PASSES after registering the pgvector codec on the `db_engine` fixture

---

## Attempt 1 — 2026-07-03T06:20:36Z

### Implementation Plan
- Confirm the current red state on `test_ac4_correction_written_with_embedding` against the live Docker stack (Postgres `app_postgres` + Ollama, already up)
- Add `from pgvector.psycopg2 import register_vector` and `event` to the sqlalchemy import in `test_memory_system.py`
- Register the vector codec via a SQLAlchemy `connect` event on `db_engine`, before `yield engine`
- Re-run the target test to confirm green, then `just lint` and `just test-unit`

### Files Changed
- modified `apps/backend/tests/integration/test_memory_system.py` — import `register_vector`/`event`; register the pgvector codec on the `db_engine` fixture's `connect` event

### New Tests
(none — test-fixture-only change per task scope; no new test code, only a fixture fix)

### Key Decisions
- Local venv was missing `greenlet` (uv.lock's marker for it only matches `platform_machine == 'aarch64'`, but macOS Apple Silicon reports `arm64` via `platform.machine()`, so `uv sync --all-extras` silently skips it on this machine). This blocks the sync SQLModel engine in `second_brain/db/session.py` from bridging its `+asyncpg`-suffixed `DATABASE_URL` and errors before ever reaching the codec bug under test. Installed `greenlet` directly into the worktree's `.venv` via `uv pip install greenlet` (not `uv add`) purely to unblock local verification — did not touch `pyproject.toml` or `uv.lock`, and `git status` after confirms no tracked files changed. This is a pre-existing environment gap outside RC1-4 scope and is not fixed by this task; flagging it rather than silently working around it.
- Also discovered the test file's own docstring recommends `DATABASE_URL=postgresql+asyncpg://...`, but `apps/backend/.env.template` uses `postgresql+psycopg2://...`. The `+asyncpg` form breaks `db/session.py`'s sync `create_engine` (used by `memory_persistence_node`'s writes) independently of the codec bug. Used the `.env.template`'s `+psycopg2` form to run the test, which reproduced the exact target failure mode (`assert 12764 == 1024`) cleanly. No production/doc file was changed for this — out of scope for RC3.
- Confirmed red state first: ran the target test unmodified and got `AssertionError: assert 12764 == 1024` (embedding read back as a 12764-char string) — matches the plan's expected failure exactly.

### Lint Output
PASS

### Test Output
PASS (209 passed, 0 new — test-fixture-only fix; target integration test `test_ac4_correction_written_with_embedding` also confirmed PASSED manually against the live stack, going from `assert 12764 == 1024` (red) to PASSED (green))

### Commit
`pending`

### Outcome: success
