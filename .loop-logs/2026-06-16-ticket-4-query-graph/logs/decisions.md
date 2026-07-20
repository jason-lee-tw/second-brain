# Decisions & Challenges — 2026-06-16-ticket-4-query-graph

## task-1-secondbrainstate-typeddicts-unit-test-conftest

### Key decisions
- Did not import unused TypedDicts (`WebResult`, `MemoryItem`, etc.) into test/conftest files — ruff `F401` would fail since neither new test nor `make_state()` references them.
- Wrapped a comment/shortened a docstring across two lines to fix ruff E501 — mechanical, no semantic change.

## task-2-pii-service

### Key decisions
- Used the plan's exact PII test inputs verbatim — Presidio's default recognizers caught all formats on the first attempt.
- Did not recreate `services/__init__.py`/`test_services/__init__.py` — both already existed.
- Kept the module docstring-free per existing `services/embeddings.py`/`services/tavily.py` style.

## task-3-piiredactionnode-inbound-outbound

### Key decisions
- Deviated from the plan's literal "What is the capital of France?" no-PII test example — Presidio's `LOCATION` recognizer (from the already-shipped Task 2 service) flags country names as PII, an existing repo behavior out of this task's scope. Swapped to a verified-clean example rather than modifying the shared `services/pii.py`, which other in-flight parallel tasks depended on.

### Challenges faced
- Attempt 1 failed: ruff E501 (line too long) in the new test file.
- Attempt 2 failed: the plan's own example text ("What is the capital of France?") triggered a genuine false-positive PII match from the already-shipped `services/pii.py` LOCATION recognizer — not a bug in this task, but exposed by it.

## task-4-memoryretrievalnode-stub

### Key decisions
- Used a one-line docstring instead of the plan's multi-line version, trimmed twice to satisfy ruff's E501 limit.

## task-5-orchestrator-node

### Key decisions
- Passed `settings.anthropic_api_key` (a `SecretStr`) directly to `ChatAnthropic`'s `anthropic_api_key` field rather than calling `.get_secret_value()` — the field accepts `SecretStr` natively.
- Kept `"claude-haiku-4-5"` as a hardcoded literal (no new `Settings` field) to avoid merge conflicts with sibling parallel tasks touching `config.py`.

## task-6-rag-retrieval-node

### Key decisions
- Reused the shared `embed_text` from `second_brain.services.embeddings` instead of writing a second Ollama HTTP client.
- Added a small private `_asyncpg_dsn` helper inside `rag_retrieval.py` to strip the `+psycopg2` SQLAlchemy suffix from `settings.database_url` before handing it to `asyncpg` — kept local rather than touching shared `config.py`, to avoid conflicts with parallel sibling tasks.

## task-7-web-research-node

### Key decisions
- Kept rate limiting (`asyncio.sleep(1)`) in the node, not the service — the service function stays a reusable plain Tavily wrapper; the node owns graph-specific throttling policy.
- Reused the existing module-level `AsyncTavilyClient` in `services/tavily.py` rather than instantiating a second client.

## task-8-synthesis-node

### Key decisions
- Sourced the Anthropic API key explicitly from `settings.anthropic_api_key`, matching the repo's existing explicit-credential convention and avoiding merge conflicts with sibling tasks touching shared config.

## task-9-query-graph-with-langgraph-checkpointing

### Key decisions
- Imported `Send` from `langgraph.types` instead of the plan's `langgraph.constants` — the installed `langgraph==0.6.11` deprecates the `constants` path.
- Fixed the plan's own smoke-test mock setup (it left `AsyncConnectionPool.open()` as a bare `MagicMock`, not an `AsyncMock`, causing a real `TypeError` against the actual implementation) — a test-mock correction, not an implementation change.
- `build_query_graph()` takes the DSN as-is with no `+psycopg2` stripping inside — stripping is deferred to the caller (Task 10), keeping this a pure "DSN in, compiled graph out" function.

## task-10-api-schemas-and-query-router

### Key decisions
- `shutdown()` reaches the connection pool via `_graph.checkpointer.conn` (since `build_query_graph()` never returns the pool it opens internally), guarded by `getattr` so it degrades to a no-op if that internal shape ever changes.
- Router tests mock the `_get_graph` accessor function rather than the module-level `_graph` singleton directly, and build a standalone `FastAPI()` app around just the router (Task 11 owns registering it on the main app).

## task-11-register-router-in-main-py

### Key decisions
- Imported both the `query` module (for `.shutdown()`) and the `query_router` name (for `include_router`), mirroring the existing `from second_brain.nodes import ingestion_agent` pattern already used for other teardown calls.

## task-12-integration-tests-ac-5-ac-6-ac-10

### Key decisions
- Found a real bug in already-merged production code (not introduced by this task): `build_query_graph()`'s `AsyncConnectionPool` defaults to `autocommit=False`, which breaks `AsyncPostgresSaver.setup()`'s `CREATE INDEX CONCURRENTLY` migration on any fresh database. Worked around it inside the test file only (a fixture pre-creating checkpoint tables via an autocommit connection), explicitly flagging the real fix (`autocommit=True` on the pool) for follow-up rather than silently masking it.
- Used fresh `uuid4().hex[:8]`-suffixed session IDs per test to avoid collisions on the shared live Postgres.

## Review fixes

- **F1** (blocking): `AsyncConnectionPool(conninfo=postgres_url, open=False)` in `build_query_graph()` defaulted to `autocommit=False`, breaking `AsyncPostgresSaver.setup()`'s `CREATE INDEX CONCURRENTLY` migrations on a fresh database — exactly the bug Task 12 had already found and worked around in tests. Root-cause verified against the installed `langgraph-checkpoint-postgres`/`psycopg` package internals (write path uses `conn.pipeline()`/`conn.transaction()` for atomicity, so it's correct under `autocommit=True`, matching upstream's own `from_conn_string()` pattern). Fix: pass `kwargs={"autocommit": True}` to the pool; delete the now-dead test workaround; add a genuinely isolated (uuid-named schema, not shared-state-mutating) regression test that reproduces the exact failure pre-fix and passes post-fix.
- **F2** (blocking): `synthesize_answer`/`redact_outbound` never constructed an `AIMessage`, so the assistant's own answers were never appended to `state["messages"]` — multi-turn context only ever contained Human turns, silently undermining conversation coherence and a later ticket's stated assumption about `messages[-2]`. Fix: compute the redacted `final_answer` once in `redact_outbound` (the last node before `END`) and return both `final_answer` and `messages: [AIMessage(content=redacted)]` — guaranteeing only ever-redacted content enters checkpointed history, never the raw pre-redaction answer even transiently.
- **F3** (important): `/query`'s exception handler forwarded the raw exception string to API clients, risking credential/DSN leakage with no server-side logging. Fix: log the full exception server-side (`exc_info=True`); return a generic, credential-free message to the client.
- **F4** (important): `retrieve_from_rag` opened a brand-new `asyncpg` connection per request instead of reusing a pool. Fix: lazily-created shared `asyncpg.Pool` with `register_vector` wired via the pool's `init` callback, plus a `shutdown()` wired into `main.py`'s lifespan (a follow-up review round caught that the shutdown hook was added but not actually wired in — fixed in a second pass).
