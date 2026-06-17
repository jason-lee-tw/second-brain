```
pyproject.toml               ← uv workspace root (members: apps/backend, apps/eval)
uv.lock                      ← single workspace lockfile
ruff.toml                    ← shared lint/format config
apps/backend/
  src/second_brain/
    config.py             ← pydantic-settings (Settings); validates all env vars at startup
    main.py               ← FastAPI app + /health
    api/
      routers/            ← endpoint routers (query, ingest) (planned)
      schemas.py          ← request/response schemas
    db/
      models.py           ← all 5 SQLModel table definitions (source of truth for types)
      session.py          ← engine + get_session FastAPI dependency
    graphs/               ← LangGraph graph definitions (query graph, ingestion graph)
    nodes/                ← LangGraph node implementations
    services/
      chunking.py         ← hybrid document chunking (headings → paragraphs → sentences) (planned)
      embeddings.py       ← Ollama embedding client (qwen3-embedding:0.6b) (planned)
      pii.py              ← Presidio PII redaction (planned)
      tavily.py           ← Tavily web search/crawl (planned)
    observability/
      tracing.py          ← setup_tracing() + @trace_node decorator (planned)
  alembic/
    versions/             ← migration files (001_initial_schema.py, ...)
  tests/
    unit/                 ← unit tests (no DB required)
    integration/          ← migration + DB integration tests (requires running postgres)
  pyproject.toml          ← second-brain package (runtime + dev deps)
  pytest.ini              ← backend pytest config (testpaths, asyncio_mode, pythonpath)
  alembic.ini
apps/eval/
  pyproject.toml          ← second-brain-eval package (ragas + second-brain workspace dep)
  dataset/                ← curated eval pairs (30–50 after manual curation)
  generate_dataset.py     ← Claude generates ~100 Q&A pairs from ingested docs (planned)
  baseline.py             ← no-RAG baseline (Claude only, no retrieval) (planned)
  run_eval.py             ← full RAGAS evaluation (planned)
  compare.py              ← markdown report with RAG vs baseline delta (planned)
temp/
  pending-digest-docs/    ← drop .md files here to ingest
  processed/              ← moved here after successful ingestion
  failed/                 ← moved here after 3 retries exhausted
docker-compose.yml
Justfile
docker/
  Dockerfile.backend      ← backend service image build file
  ollama-checker.sh       ← waits for Ollama to be ready before starting backend
scripts/
  init.sh                 ← installs git hooks and runs uv sync --all-extras
  start-ollama.sh         ← starts the Ollama service
  stop-ollama.sh          ← stops the Ollama service
```
