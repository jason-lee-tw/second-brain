# Task 3: Close httpx and anthropic clients on shutdown

## Attempt 1 — 2026-06-19

**Goal:** Add `aclose()` teardown calls in `main.py` lifespan for `embeddings._client` and `ingestion_agent._anthropic`.

**Plan:**
1. Write failing test in `tests/unit/test_main.py` that patches `_client` and `_anthropic`, runs lifespan, asserts `aclose()` called on both
2. Confirm test fails (aclose not called yet)
3. Add imports and aclose() calls to lifespan in `main.py`
4. Run `just lint` and `just test-unit`

**Files to change:**
- `apps/backend/src/second_brain/main.py` — add imports + teardown
- `apps/backend/tests/unit/test_main.py` — new file with lifespan test

## Result — Attempt 1 SUCCESS

- `just lint`: all checks passed
- `just test-unit`: 76 passed, 0 failed
- Committed: `fix(main): close httpx and anthropic clients on shutdown`

**Key finding:** `anthropic.AsyncAnthropic` uses `close()` (async), not `aclose()`. Used correct method.
**Key finding:** Tests must mock `setup_tracing` to avoid polluting the global OTel TracerProvider state, which would break `test_observability` tests that rely on setting their own in-memory provider.
