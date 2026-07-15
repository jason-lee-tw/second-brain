# Business Index

Source: docs/business/000-index.md
Primary-Topic: project-requirements
Secondary-Topics: implementation-plan, workflow-design

## Key Concepts

- This is the index/table-of-contents for the `docs/business/` folder — it lists four business documents with one-sentence summaries each, forming the entry point for requirements/planning context.
- `001-raw-requirement.md` — the original capstone assignment brief. Describes a multi-agent "Second Brain" system requiring RAG (retrieval-augmented generation), a persistent memory subsystem, OTEL-based observability/tracing, and a PII guardrail (privacy/redaction safeguard).
- `002-project-requirement-document.md` — the full Project Requirement Document (PRD). Covers: tech stack decisions, API design (endpoint shapes/contracts), agent roles (division of responsibility across the multi-agent system), memory system design (how conversational/fact memory persists and is retrieved), and 10 concrete acceptance criteria that define "done" for the project.
- `003-implementation.md` — the implementation plan expressed as a six-ticket sequence, ordered: (1) Infrastructure, (2) OTEL (observability wiring), (3) Ingestion (file/URL ingestion pipeline), (4) Query Graph (the LangGraph-based query flow), (5) Memory (persistent memory subsystem), (6) Evaluation (RAGAS-based evaluation harness). Each ticket has its own stated goal and deliverables.
- `004-workflow-design.md` — visual/behavioral design captured as Mermaid diagrams, covering four distinct flows: the query graph (a 9-node agent flow handling incoming queries), the ingestion graph (covering both file-based and URL-based ingestion paths), the document chunking strategy (how source documents are split before embedding/storage), and the memory lifecycle (covering both "fact" memory and "correction" memory — i.e., how learned facts and user corrections to the model's answers are created, stored, and retrieved over time).
- Overall theme: this index sits at the top of the requirements-to-implementation chain — raw ask → formal PRD → ticket breakdown → workflow/behavioral design — giving a single place to trace how the Second Brain project's business requirements flow into its technical execution plan.
