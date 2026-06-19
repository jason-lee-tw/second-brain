# Review Fix Plan: feat/003-ingestion

## Goal
Address the four 🟡 findings from the enhanced-review of feat/003-ingestion.

---

### Task 1: Make url_to_slug public

**Finding:** F1 — `ingest.py` imports `_url_to_slug` (private) from `tavily.py`, crossing a module boundary.

**Changes required:**
- `apps/backend/src/second_brain/services/tavily.py`: rename `_url_to_slug` → `url_to_slug`
- `apps/backend/src/second_brain/api/routers/ingest.py`: update import to `url_to_slug`
- `apps/backend/tests/unit/test_services/test_tavily.py`: update any references to `_url_to_slug`
- `apps/backend/tests/unit/test_api/test_routers/test_ingest.py`: update any references

**Acceptance:** `just lint && just test-unit` pass; no `_url_to_slug` remains in any source file.

---

### Task 2: Validate URLs with AnyHttpUrl

**Finding:** F2 — `IngestUrlRequest.urls: list[str]` accepts any string; malformed input reaches Tavily with no 422.

**Changes required:**
- `apps/backend/src/second_brain/api/schemas.py`: change `urls: list[str]` → `urls: list[AnyHttpUrl]`
- `apps/backend/tests/unit/test_api/test_schemas.py`: add test asserting a non-URL string raises a validation error; existing tests must still pass
- `apps/backend/tests/unit/test_api/test_routers/test_ingest.py`: update any test that constructs `IngestUrlRequest` with bare strings to use valid HTTP URLs

**Acceptance:** `just lint && just test-unit` pass; posting a non-URL to `/ingest/url` returns 422.

---

### Task 3: Close httpx and Anthropic clients on shutdown

**Finding:** F3 — module-level `httpx.AsyncClient` and `anthropic.AsyncAnthropic` are never closed; FastAPI lifespan only manages `TracerProvider`.

**Changes required:**
- `apps/backend/src/second_brain/main.py`: in the lifespan, after `yield`, call:
  - `await embeddings._client.aclose()`
  - `await ingestion_agent._anthropic.aclose()`
- Import both modules in `main.py`
- `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py` or a new test: verify no ResourceWarning is emitted (or simply confirm the lifespan teardown calls aclose)

**Acceptance:** `just lint && just test-unit` pass; no `ResourceWarning: Unclosed client session` in test output.

---

### Task 4: Document sync-DB-in-async with ponytail comment

**Finding:** F4 — `_do_ingest` uses synchronous `Session(engine)` inside `async def`, blocking the event loop.

**Changes required:**
- `apps/backend/src/second_brain/nodes/ingestion_agent.py`: add comment above `with Session(engine) as session:`:
  ```python
  # ponytail: sync session in async fn — upgrade to AsyncSession when multi-file concurrency lands
  ```

**Acceptance:** `just lint && just test-unit` pass; comment is present in the file.
