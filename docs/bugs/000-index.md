# Bugs Index

- [001-fix-typecheck-error.md](001-fix-typecheck-error.md) — Decisions for fixing 50 basedpyright errors across 12 files using targeted `# type: ignore`, per-node output TypedDicts, and a `get_str_content` util helper.
- [002-query-graph-autocommit.md](002-query-graph-autocommit.md) — P0: `POST /query` returned 500 because the psycopg3 pool lacked `autocommit=True` (LangGraph DDL requirement), plus a follow-up asyncpg JSONB decoding bug fixed by registering a pool-level codec.
- [003-integration-test-failures.md](003-integration-test-failures.md) — P1: 8/20 `just test-integration` failures traced to 4 independent causes — an untyped SQL parameter silently disabling the memory conflict-check threshold, async singletons not surviving pytest-asyncio's per-test event loop, a raw-SQL test fixture missing pgvector decoding, and a stale test asserting an FK that was deliberately dropped.
