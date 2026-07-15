# Tech Stack

The Second Brain runs on Python 3.13 + FastAPI + LangGraph, storing vectors in Postgres/pgvector, tracing through Arize Phoenix/OTEL, and evaluated with RAGAS — the mandatory subset of this stack is fixed by the capstone assignment itself.

## Key Concepts

- **Language & web framework**: Python 3.13, served via FastAPI.
- **Agent orchestration**: LangGraph.
- **Database**: PostgreSQL 16 with the `pgvector` extension for vector similarity search; SQLModel is the ORM layer, Alembic handles schema migrations.
- **Observability**: Arize Phoenix via OpenTelemetry (OTEL), with the Phoenix UI served at `localhost:6006`; the `openinference-instrumentation-langchain` package instruments LangChain/LangGraph spans specifically.
- **Embedding model**: `qwen3-embedding:0.6b` served via Ollama at `localhost:11434`, producing 1024-dimensional embeddings.
- **LLM tiers**: `claude-haiku-4-5` (lightweight — routing, web research, memory extraction) and `claude-sonnet-4-6` (synthesis/eval — final answer synthesis and LLM-as-judge in evaluations).
- **Web search/crawl**: Tavily SDK, used to crawl URLs and retrieve web content.
- **PII redaction**: Presidio, configured with broad scope covering names, emails, phone numbers, addresses, government IDs, financial data, and medical data.
- **Evaluation**: RAGAS, using `context_recall`, `context_precision`, `faithfulness`, and `answer_relevancy`, to prove measurable improvement of the RAG system over a no-RAG baseline.
- **Containerisation**: Docker Compose orchestrates all services (backend, database, Phoenix, etc.).

## Capstone-Mandated Subset

The capstone assignment fixes a subset of this stack as required, independent of implementation choices made later:

- Python
- LangGraph
- Postgres Vector (pgvector-style vector storage in Postgres)
- Arize Phoenix (with Postgres) for observability/tracing
- Docker (via docker compose)
- Tavily SDK — for web search, web crawling, and extracting data from websites

## Sources

- Tech Stack — `docs/codebase/001-tech-stack.md`
- "Second Brain" Capstone Assignment — `docs/business/001-raw-requirement.md`

## Related Topics

- [[capstone-requirements]]
- [[system-architecture]]
- [[otel-phoenix-tracing]]
- [[langchain-otel-instrumentation]]
- [[evaluation-harness]]
- [[pgvector-embeddings]]
- [[docker-compose]]
- [[dependency-management]]
- [[infrastructure-setup]]
- [[repo-structure]]
- [[multi-agent-architecture]]
- [[codebase-overview]]
- [[ragas-collections-migration]]
