# Tech Stack

Source: docs/codebase/001-tech-stack.md
Primary-Topic: tech-stack
Secondary-Topics: observability, evaluation

## Key Concepts

- Language: Python 3.13.
- Web framework: FastAPI.
- Agent orchestration: LangGraph.
- Database: PostgreSQL 16 with the pgvector extension for vector similarity search.
- ORM + migrations: SQLModel for the ORM layer, Alembic for schema migrations.
- Observability: Arize Phoenix using OpenTelemetry (OTEL); Phoenix UI served at `localhost:6006`; `openinference-instrumentation-langchain` package instruments LangChain/LangGraph spans specifically.
- Embedding model: `qwen3-embedding:0.6b` served via Ollama at `localhost:11434`, producing 1024-dimensional embeddings.
- LLM — lightweight tier: `claude-haiku-4-5`, used for routing, web research, and memory extraction tasks.
- LLM — synthesis/eval tier: `claude-sonnet-4-6`, used for final answer synthesis and as the LLM-as-judge in evaluations.
- Web search/crawl: Tavily SDK — used to crawl URLs and retrieve web content.
- PII redaction: Presidio, configured with broad scope covering names, emails, phone numbers, addresses, government IDs, financial data, and medical data.
- Evaluation framework: RAGAS, using the metrics `context_recall`, `context_precision`, `faithfulness`, and `answer_relevancy` — used to prove measurable improvement of the RAG system over a no-RAG baseline.
- Containerisation: Docker Compose orchestrates all services (backend, database, Phoenix, etc.).
