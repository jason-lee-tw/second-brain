# Tech Stack

| Component            | Technology                                                                         |
| -------------------- | ---------------------------------------------------------------------------------- |
| Language             | Python 3.12                                                                        |
| Web framework        | FastAPI                                                                            |
| Agent orchestration  | LangGraph                                                                          |
| Database             | PostgreSQL 16 + pgvector                                                           |
| ORM + migrations     | SQLModel + Alembic                                                                 |
| Observability        | Arize Phoenix (OTEL) — UI at `localhost:6006`                                      |
| Embedding model      | `qwen3-embedding:0.6b` via Ollama (`localhost:11434`, dim=1024)                    |
| LLM — lightweight    | `claude-haiku-4-5` (routing, web research, memory extraction)                      |
| LLM — synthesis/eval | `claude-sonnet-4-6` (final answers + LLM-as-judge evals)                           |
| Web search/crawl     | Tavily SDK                                                                         |
| PII redaction        | Presidio (broad scope — names, emails, phones, addresses, IDs, financial, medical) |
| Evaluation           | RAGAS (`context_recall`, `context_precision`, `faithfulness`, `answer_relevancy`)  |
| Containerisation     | Docker Compose                                                                     |
