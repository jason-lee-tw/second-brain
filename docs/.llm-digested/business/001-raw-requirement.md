# "Second Brain" Capstone Assignment

Source: docs/business/001-raw-requirement.md
Primary-Topic: capstone-requirements
Secondary-Topics: tech-stack, multi-agent-architecture

## Key Concepts

- Overview: build a "second brain" system for personal use, developed using evaluation-driven development.
- Core goal: design a multi-agent system that ingests data from various sources (notes, meeting transcriptions, cooking recipes, or any personal content).
- The system must store ingested information for semantic retrieval.
- The system must maintain persistent memory of conversations and user preferences.
- The system must demonstrate measurable improvement over basic chatbots through rigorous evaluation.
- Must include at least three specialized agents working together to research, synthesize information, and learn from interactions.
- Must provide a simple interface for the user to interact with the second brain.
- Must show clear evidence via evaluation metrics of concrete benefits from: multi-agent architecture, RAG implementation, and/or memory systems — versus simpler approaches.
- In-scope requirements:
  - Use LangGraph (for agent orchestration/graphs).
  - Use Eval Driven Development — AI output must be evaluated.
  - Implement OTEL observability (OpenTelemetry tracing).
  - Implement RAG (Retrieval-Augmented Generation) for content such as notes and meeting transcriptions.
  - Implement basic Memory.
  - Add a guardrail to remove PII (personally identifiable information) from memory/message history.
  - Store data locally (no cloud storage).
  - Optional: use MCP servers for some functionality.
  - Optional (recommended): implement multi-agent orchestration using any multi-agent pattern.
- Out-of-scope items:
  - Large scale web scraping or document ingestion.
  - Cloud hosting.
  - Exposing anything to the internet.
  - A polished/"really nice looking" GUI.
  - Complicated observability setup.
- Suggested data sourcing: learners are encouraged to ingest meaningful, real-world content to build a richer, more useful second brain (no specific source mandated).
- Model choice: learners may use either Claude or Gemini models for the capstone, contingent on the $5 credit not being exhausted; recommendation to try both models and compare performance.
- Required tech stack:
  - Python
  - LangGraph
  - Postgres Vector (pgvector-style vector storage in Postgres)
  - Arize Phoenix (with Postgres) for observability/tracing
  - Docker (via docker compose)
  - Tavily SDK — used for web search, web crawling, and extracting data from websites
