# Codebase Overview

`docs/codebase/` is the authoritative home for the Second Brain project's architecture, tech-stack, repo-layout, and database-schema documentation, organized as a table-of-contents plus four sub-documents.

## Key Concepts

- `docs/codebase/000-index.md` is the table-of-contents for the `docs/codebase/` folder — it links out to four sub-documents, each with a one-sentence summary.
- `001-tech-stack.md` — full tech stack reference table covering language, frameworks, models, observability, and evaluation tooling used across the project.
- `002-repo-structure.md` — annotated workspace directory tree showing every key file and its purpose across the monorepo.
- `003-system-architecture.md` — high-level architecture diagram documenting Docker networks, container startup order, connection pool architecture, workspace structure, and observability setup (Phoenix/OTEL).
- `004-database.md` — documents the DB access strategy (the two-pattern rule: `asyncpg` for pgvector reads, SQLModel sync `Session` for writes), the connection pool inventory, and the full schema ER diagram.
- Downstream readers (agents, contributors) are expected to start at this index to locate the right sub-document rather than searching the codebase directly.

## Sources

- Codebase Index — `docs/codebase/000-index.md`

## Related Topics

- [[system-architecture]]
- [[database-schema]]
- [[tech-stack]]
- [[repo-structure]]
