# Project Requirements

`docs/business/` is the authoritative home for the Second Brain project's requirements-to-implementation chain — raw capstone ask, PRD, ticket breakdown, and workflow design — organized as a table-of-contents plus four sub-documents.

## Key Concepts

- `docs/business/000-index.md` is the table-of-contents for the `docs/business/` folder — it lists four business documents with one-sentence summaries each, forming the entry point for requirements/planning context.
- `001-raw-requirement.md` — the original capstone assignment brief. Describes a multi-agent "Second Brain" system requiring RAG, a persistent memory subsystem, OTEL-based observability/tracing, and a PII guardrail.
- `002-project-requirement-document.md` — the full Project Requirement Document (PRD). Covers tech stack decisions, API design, agent roles, memory system design, and 10 concrete acceptance criteria that define "done" for the project.
- `003-implementation.md` — the implementation plan expressed as a six-ticket sequence: Infrastructure, OTEL, Ingestion, Query Graph, Memory, Evaluation.
- `004-workflow-design.md` — visual/behavioral design captured as Mermaid diagrams, covering the query graph flow, the ingestion graph flow, the document chunking strategy, and the memory lifecycle (fact memory and correction memory).
- Overall theme: this index sits at the top of the requirements-to-implementation chain — raw ask → formal PRD → ticket breakdown → workflow/behavioral design — giving a single place to trace how the Second Brain project's business requirements flow into its technical execution plan.

## Sources

- Business Index — `docs/business/000-index.md`

## Related Topics

- [[capstone-requirements]]
- [[second-brain-requirements]]
- [[implementation-plan]]
- [[query-workflow]]
- [[second-brain-architecture]]
