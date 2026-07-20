# Code Review — Round 1

**Timestamp:** 2026-07-20T06:08:00Z
**Loop iteration:** 1 of ≤5
**Model tier:** Sonnet (diff: 1840 lines / 30 files changed — over the 20-file threshold, session model already runs 1M-context Sonnet 5)

## Findings

| ID  | Severity  | Summary | Evidence (file:line) |
| --- | --------- | ------- | --------------------- |
| F1  | blocking  | `AsyncConnectionPool(conninfo=postgres_url, open=False)` defaults to `autocommit=False`. `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY` migrations, which Postgres refuses inside a transaction block — breaks `build_query_graph()` on any genuinely fresh database (no pre-existing checkpoint tables). | `apps/backend/src/second_brain/graphs/query_graph.py:42-46` |
| F2  | blocking  | `synthesize_answer`/`redact_outbound` never construct/return an `AIMessage`, so the assistant's `final_answer` is never appended to `state["messages"]`/the checkpoint. Multi-turn synthesis context only ever contains prior Human turns; violates spec's "redact final_answer before it is appended to messages" sequencing; breaks Ticket 5's assumption that `messages[-2]` is the prior assistant response. | `apps/backend/src/second_brain/nodes/synthesis.py:100-104`; `apps/backend/src/second_brain/nodes/pii_redaction.py:29-31` |
| F3  | important | `/query`'s exception handler forwards the raw exception string to the client with no server-side logging — risks leaking DSN/credentials in error text, and leaves nothing for operators to debug from. | `apps/backend/src/second_brain/api/routers/query.py:76-81` |
| F4  | important | `retrieve_from_rag` opens a brand-new `asyncpg.connect()` per query instead of a shared pool — full handshake on every RAG-routed request; a third distinct Postgres access mechanism alongside `psycopg`/`AsyncConnectionPool` (checkpointer) and SQLModel/SQLAlchemy (ingestion). | `apps/backend/src/second_brain/nodes/rag_retrieval.py:18,56` |
| F5  | minor     | `database_url.replace("+psycopg2", "")` DSN-stripping duplicated 3x — accepted tradeoff during parallel implementation, worth consolidating now. | `nodes/rag_retrieval.py:9-11`; `api/routers/query.py:18-20` |
| F6  | minor     | Web-research rate limiting is a per-call local `asyncio.sleep(1)`, not a real global limiter; adds fixed 1s latency to every web-routed query even absent a burst. | `nodes/web_research.py` |
| F7  | minor     | `_get_graph()` lazy singleton has no lock — concurrent cold-start requests can race into `build_query_graph()` more than once, leaking connection pools. | `api/routers/query.py:15-22` |
| F8  | minor     | `main.py` imports the query router module under two names solely to reach both `.router` and `.shutdown()` — redundant import. | `main.py:7,9` |

## Disposition

- Actionable (blocking + important) — to fix this iteration: F1, F2, F3, F4
- Deferred (minor — NOT handled yet): F5, F6, F7, F8
