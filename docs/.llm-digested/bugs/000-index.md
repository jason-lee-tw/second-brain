# Bugs Index

Source: docs/bugs/000-index.md
Primary-Topic: known-issues
Secondary-Topics: postgres-connection-pooling, integration-testing

## Key Concepts

- This file is the table-of-contents for the `docs/bugs/` folder — an alphabetical/numbered list of bug write-ups, each with a one-line summary; it is not itself a bug write-up.
- 001-fix-typecheck-error.md — Decisions for fixing 50 basedpyright errors across 12 files using targeted `# type: ignore`, per-node output TypedDicts, and a `get_str_content` util helper.
- 002-query-graph-autocommit.md — P0: `POST /query` returned 500 because the psycopg3 pool lacked `autocommit=True` (a LangGraph DDL requirement), plus a follow-up asyncpg JSONB decoding bug fixed by registering a pool-level codec.
- 003-integration-test-failures.md — P1: 8/20 `just test-integration` failures traced to 4 independent causes: an untyped SQL parameter silently disabling the memory conflict-check threshold, async singletons not surviving pytest-asyncio's per-test event loop, a raw-SQL test fixture missing pgvector decoding, and a stale test asserting a foreign key that was deliberately dropped.
- 004-synthesis-max-tokens-truncation.md — P1: `POST /query` 500s when the synthesis LLM completion is truncated by the (unset, defaulted-to-1024) `max_tokens` cap before the required `reasoning` field is written; a latent defect made load-bearing by this branch's model swap to the more verbose `claude-sonnet-5`. This is the newest entry added to the index.
