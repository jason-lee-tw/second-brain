# pgvector Embeddings

Vector columns (`VECTOR(1024)`, via `qwen3-embedding:0.6b`) power cosine-similarity retrieval across the codebase, but two independent driver-level pitfalls — asyncpg parameter type coercion on write, and missing codec registration on raw-SQL reads — have each silently corrupted embedding behavior without raising an error.

## Key Concepts

- Cosine-distance retrieval uses the `<=>` operator directly in SQL, e.g. `WHERE (embedding<=>$1) < $2` — the query itself is simple, but binding the comparison parameter safely is not.
- Embedding columns require correct type handling on **both** the write path (asyncpg bind parameters) and the read path (driver-level vector codec registration) — getting either wrong fails silently rather than raising, which is why both bugs below went undetected until an integration-test run finally exercised them.
- For evaluation/retrieval outside the ORM, an embedding vector is sent to Postgres as a string literal cast to the column type — e.g. `"[v1,v2,...]"::vector` — when building ad hoc cosine-distance queries against `document_chunks` from a plain SQL client.
- Questions or documents are embedded via `langchain_ollama.OllamaEmbeddings(model="qwen3-embedding:0.6b")` before being used in any pgvector similarity query — the same embedding model used for storage, so retrieval and storage vectors are comparable.

## Known Pitfalls

- **Untyped bind-parameter arithmetic silently truncates a float to an integer.** A conflict-check query wrote `WHERE (embedding<=>$1) < (1 - $2)` with `$2` bound to a Python float (0.95, `settings.memory_conflict_threshold`). Because `$2` only appears inside `1 - $2`, Postgres infers `$2`'s type from the untyped integer literal `1`, so asyncpg encodes 0.95 as an `integer` parameter and truncates it to `0` — `(1 - $2)` then evaluates to `1`, matching almost every row instead of only near-duplicates. No error is raised; the query just returns the wrong rows. Fix: precompute the derived value in Python (`max_distance = 1 - threshold`) and bind it directly, e.g. `WHERE (embedding<=>$1) < $2` — never do arithmetic on a bind parameter inside raw SQL when one operand's type isn't otherwise pinned.
- **A driver without a registered vector codec returns text, not floats, from a `VECTOR` column.** A raw-SQL test fixture opened its own `psycopg2` connection (via a plain `create_engine(sync_url)`) with no pgvector adapter registered; reading an `embedding` column back returned the pgvector text literal (a string like `'[-0.0073,...]'`, 12764 characters) instead of a parsed `list[float]` of dimensionality 1024. The ORM path (SQLModel + `pgvector.sqlalchemy.Vector` column type) decodes vectors automatically because the codec is registered on that engine — but any connection opened outside the ORM must register it itself. Fix: register `pgvector.psycopg2.register_vector` on the raw connection via a SQLAlchemy `connect` event hook before querying.
- Both pitfalls are driver/codec-level, not schema-level — the underlying `VECTOR(1024)` columns and cosine-distance semantics were correct throughout; only the client-side encode/decode step was broken.

## Open Questions

- **memory_conflict_threshold default**: this page states the value bound was `0.95`, but [[memory-system]], [[query-workflow]], and [[second-brain-architecture]] state the default is `0.85`. Unresolved — needs source verification.

## Sources

- Bug: `just test-integration` — 8/20 tests failing — `docs/bugs/003-integration-test-failures.md`
- Offline Evaluation Harness Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-6-evaluation.md`

## Related Topics

- [[integration-testing]]
- [[evaluation-harness]]
- [[database-schema]]
- [[database-access-patterns]]
- [[postgres-connection-pooling]]
- [[memory-system]]
- [[known-issues]]
- [[asyncpg-jsonb-codec]]
- [[capstone-requirements]]
- [[document-ingestion-pipeline]]
- [[query-graph]]
- [[query-workflow]]
- [[second-brain-architecture]]
- [[tech-stack]]
