# Known Issues

Index of documented bugs and their root-cause decisions in `docs/bugs/`, spanning type-checking cleanup, a P0 query-graph autocommit/JSONB-decoding bug, a P1 integration-test investigation with four independent root causes, and a P1 synthesis `max_tokens` truncation bug.

## Key Concepts

- `docs/bugs/000-index.md` is the table-of-contents for the `docs/bugs/` folder — an alphabetical/numbered list of bug write-ups, each with a one-line summary; it is not itself a bug write-up. The bugs index records not just the fix but the root-cause decision/reasoning behind each bug, intended as durable institutional knowledge; severity labels P0/P1 indicate production impact.
- **001 — Fix typecheck errors**: 50 basedpyright errors across 12 files, fixed with targeted `# type: ignore` comments, per-node output `TypedDict`s, and a shared `get_str_content` utility helper.
- **002 — Query graph autocommit bug (P0)**: `POST /query` returned HTTP 500 because the psycopg3 pool lacked `autocommit=True` (a LangGraph DDL requirement), plus a follow-up asyncpg JSONB decoding bug fixed by registering a pool-level codec.
- **003 — Integration test failures (P1)**: 8/20 `just test-integration` failures traced to 4 independent causes — an untyped SQL parameter silently disabling the memory conflict-check threshold, async singletons not surviving pytest-asyncio's per-test event loop, a raw-SQL test fixture missing pgvector decoding, and a stale test asserting a foreign key that was deliberately dropped.
- **004 — Synthesis `max_tokens` truncation (P1)**: `POST /query` 500s when the synthesis LLM completion is truncated by the (unset, defaulted-to-1024) `max_tokens` cap before the required `reasoning` field is written — a latent defect made load-bearing by this branch's model swap to the more verbose `claude-sonnet-5`. This is the newest entry added to the index. It has a corresponding implementation plan (`BaseAgentNode._ainvoke_structured` retry helper + raising `max_tokens` to 4096 on `SynthesisNode` and `MemoryAgentNode`) — see [[synthesis-max-tokens-truncation-fix]] for the fix detail rather than duplicating it here.

## Sources

- Bugs Index — `docs/bugs/000-index.md`
- Synthesis max_tokens Truncation Fix Implementation Plan — `docs/superpowers/plans/2026-07-13-synthesis-max-tokens-truncation-fix.md`

## Related Topics

- [[synthesis-max-tokens-truncation-fix]]
- [[otel-phoenix-tracing]]
- [[postgres-connection-pooling]]
- [[asyncpg-jsonb-codec]]
- [[integration-testing]]
- [[type-checking]]
- [[query-graph-autocommit-fix]]
- [[database-access-patterns]]
- [[memory-system]]
- [[pgvector-embeddings]]
