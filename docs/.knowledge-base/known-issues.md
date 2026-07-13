# Known Issues

Index of documented bugs and their root-cause decisions, spanning type-checking cleanup, a P0 query-graph autocommit/JSONB-decoding bug, and a P1 integration-test investigation with four independent root causes.

## Key Concepts

- The bugs index (`docs/bugs/`) records not just the fix but the root-cause decision/reasoning behind each bug, intended as durable institutional knowledge; severity labels P0/P1 indicate production impact.
- **001 — Fix typecheck errors**: 50 basedpyright (static type-checking) errors spread across 12 files. Fix approach: targeted `# type: ignore` comments used sparingly rather than broad suppression, per-node output `TypedDict`s introduced to give LangGraph node outputs precise, checkable shapes, and a shared `get_str_content` utility helper added for repeated content-extraction/type-narrowing logic across nodes.
- **002 — Query graph autocommit bug (P0)**: `POST /query` returned HTTP 500.
  - Root cause #1: the psycopg3 connection pool used by the query graph lacked `autocommit=True`, which LangGraph's checkpoint/DDL operations require (LangGraph issues DDL statements that need autocommit semantics, not wrapped in an explicit transaction). Ties to the project's dual-pool architecture — `psycopg_pool.AsyncConnectionPool` is used specifically for LangGraph's `AsyncPostgresSaver`, separate from the `asyncpg.Pool` used for RAG/memory retrieval, since the two pools use different drivers and cannot be shared.
  - Root cause #2 (follow-up bug found while fixing #1): an asyncpg JSONB decoding bug — asyncpg does not decode JSONB columns to Python objects by default, requiring a pool-level codec registration so JSONB values come back as parsed Python data instead of raw strings.
  - Fix: registered a pool-level codec for JSONB decoding on the asyncpg pool, in addition to setting `autocommit=True` on the psycopg3 pool.
- **003 — Integration test failures (P1)**: 8 of 20 `just test-integration` tests were failing. Root-cause analysis traced the 8 failures to 4 independent, unrelated causes rather than a single bug:
  1. An untyped SQL bind parameter silently disabled the memory conflict-check threshold.
  2. Async singletons did not survive pytest-asyncio's per-test event loop lifecycle.
  3. A raw-SQL test fixture was missing pgvector decoding.
  4. A stale test asserted a foreign-key constraint that had been deliberately dropped from the schema.
- Institutional lesson from 003: a batch of failing tests can stem from multiple independent root causes rather than one shared bug — each needs its own fix rather than one blanket patch.

## Sources

- Bugs Index — `docs/bugs/000-index.md`

## Related Topics

- [[postgres-connection-pooling]]
- [[asyncpg-jsonb-codec]]
- [[integration-testing]]
- [[type-checking]]
- [[query-graph-autocommit-fix]]
- [[database-access-patterns]]
- [[memory-system]]
- [[pgvector-embeddings]]
