# Codebase Index

Source: docs/codebase/000-index.md
Primary-Topic: codebase-overview
Secondary-Topics: system-architecture,database-schema

## Key Concepts

- This file is the table-of-contents for the `docs/codebase/` folder — it links out to four sub-documents and gives a one-sentence summary of each.
- [001-tech-stack.md](001-tech-stack.md) — Full tech stack reference table: covers language, frameworks, models, observability, and evaluation tooling used across the project.
- [002-repo-structure.md](002-repo-structure.md) — Annotated workspace directory tree showing every key file and its purpose across the monorepo.
- [003-system-architecture.md](003-system-architecture.md) — High-level architecture diagram; documents Docker networks, container startup order, connection pool architecture, workspace structure, and observability setup (Phoenix/OTEL).
- [004-database.md](004-database.md) — Documents the DB access strategy (the two-pattern rule: `asyncpg` for pgvector reads, SQLModel sync `Session` for writes), the connection pool inventory, and the full schema ER diagram.
- The index establishes `docs/codebase/` as the authoritative home for architecture, tech-stack, repo-layout, and database-schema documentation for the "Second Brain" knowledge-management project.
- Downstream readers (agents, contributors) are expected to start at this index to locate the right sub-document rather than searching the codebase directly.
