# Second Brain — Ticket 1: Infrastructure & Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up the complete project foundation — Docker infrastructure, FastAPI skeleton, all SQLModel database models, and Alembic migrations — so that `docker compose up` starts all services, all 5 DB tables exist with correct schema, `GET /health` returns 200, and Alembic migrations run cleanly.

**Architecture:** The backend (FastAPI + SQLModel) and its PostgreSQL database share `app_network`, while Phoenix and its own Postgres share an isolated `phoenix_network`. The backend reaches Phoenix via host port 6006 using `host.docker.internal`, maintaining network isolation as a deliberate security boundary. Database schema is managed exclusively through Alembic migrations; SQLModel models serve as both ORM table definitions and the source of truth for all type definitions referenced by later tickets.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, PostgreSQL 16 + pgvector, Alembic, pydantic-settings, Docker Compose, Arize Phoenix, pytest

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `docker-compose.yml` | Modify | Add all services and networks |
| `apps/backend/.env.template` | Modify | Document all required env vars |
| `apps/backend/pyproject.toml` | Create | Python project config and all dependencies |
| `apps/backend/Dockerfile` | Create | Build image for backend service |
| `apps/backend/src/second_brain/__init__.py` | Create | Package root |
| `apps/backend/src/second_brain/config.py` | Create | Pydantic settings loaded from env |
| `apps/backend/src/second_brain/main.py` | Create | FastAPI app and `/health` endpoint |
| `apps/backend/src/second_brain/db/__init__.py` | Create | DB sub-package root |
| `apps/backend/src/second_brain/db/models.py` | Create | All 5 SQLModel table definitions |
| `apps/backend/src/second_brain/db/session.py` | Create | SQLAlchemy engine and `get_session` dependency |
| `apps/backend/alembic.ini` | Create | Alembic configuration |
| `apps/backend/alembic/env.py` | Create | Alembic migration runner with env var override |
| `apps/backend/alembic/versions/001_initial_schema.py` | Create | First migration: all 5 tables + pgvector extension |
| `apps/backend/tests/conftest.py` | Create | Env var setup for unit tests |
| `apps/backend/tests/test_health.py` | Create | Health endpoint unit tests |
| `apps/backend/tests/unit/test_models.py` | Create | Model instantiation unit tests |
| `apps/backend/tests/integration/test_migration.py` | Create | Migration integration test |

---

### Task 1: Docker Infrastructure

**Files:**
- Modify: `docker-compose.yml`
- Modify: `apps/backend/.env.template`

- [ ] **Step 1: Replace `docker-compose.yml` with full services and networks**

```yaml
services:
  ollama-checker:
    image: curlimages/curl:latest
    env_file:
      - ./apps/backend/.env
    network_mode: host
    volumes:
      - ./docker/ollama-checker.sh:/scripts/ollama-checker.sh:ro
    entrypoint: ["sh", "/scripts/ollama-checker.sh"]
    extra_hosts:
      - "host.docker.internal:host-gateway"

  app_postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: second_brain
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: second_brain
    ports:
      - "5432:5432"
    volumes:
      - app_postgres_data:/var/lib/postgresql/data
    networks:
      - app_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U second_brain"]
      interval: 10s
      timeout: 5s
      retries: 5

  phoenix_postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: phoenix
      POSTGRES_PASSWORD: phoenix_secret
      POSTGRES_DB: phoenix
    volumes:
      - phoenix_postgres_data:/var/lib/postgresql/data
    networks:
      - phoenix_network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U phoenix"]
      interval: 10s
      timeout: 5s
      retries: 5

  phoenix:
    image: arizephoenix/phoenix:latest
    environment:
      PHOENIX_SQL_DATABASE_URL: postgresql://phoenix:phoenix_secret@phoenix_postgres:5432/phoenix
    ports:
      - "6006:6006"
    networks:
      - phoenix_network
    depends_on:
      phoenix_postgres:
        condition: service_healthy

  backend:
    build:
      context: ./apps/backend
      dockerfile: Dockerfile
    env_file:
      - ./apps/backend/.env
    ports:
      - "8000:8000"
    networks:
      - app_network
    depends_on:
      app_postgres:
        condition: service_healthy
      ollama-checker:
        condition: service_completed_successfully
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./temp:/app/temp

networks:
  app_network:
    driver: bridge
  phoenix_network:
    driver: bridge

volumes:
  app_postgres_data:
  phoenix_postgres_data:
```

> `pgvector/pgvector:pg16` is used for `app_postgres` — it ships with the pgvector shared library pre-installed. The extension still needs to be enabled per-database via `CREATE EXTENSION IF NOT EXISTS vector` inside the Alembic migration (Task 5, Step 4).
>
> The `ollama-checker` service keeps `network_mode: host` (existing behaviour, unchanged). The `backend` includes `extra_hosts: ["host.docker.internal:host-gateway"]` so it can reach Ollama and Phoenix on the host from inside Docker on Linux.

- [ ] **Step 2: Update `apps/backend/.env.template` with all required env vars**

```
# Ollama — reached from inside Docker via host port
OLLAMA_BASE_URL="http://host.docker.internal:11434"

# Application PostgreSQL (service name is the hostname inside app_network)
DATABASE_URL="postgresql+psycopg2://second_brain:secret@app_postgres:5432/second_brain"

# Anthropic
ANTHROPIC_API_KEY="sk-ant-..."

# Tavily
TAVILY_API_KEY="tvly-..."

# Phoenix OTEL — backend reaches Phoenix via host port (never via phoenix_network)
PHOENIX_COLLECTOR_ENDPOINT="http://host.docker.internal:6006/v1/traces"
```

- [ ] **Step 3: Create `.env` from the template**

```bash
cp apps/backend/.env.template apps/backend/.env
# Edit apps/backend/.env and fill in real values for:
#   ANTHROPIC_API_KEY
#   TAVILY_API_KEY
```

> `.env` is gitignored. Never commit it.

- [ ] **Step 4: Create temp directory structure**

```bash
mkdir -p temp/pending-digest-docs temp/processed temp/failed
touch temp/pending-digest-docs/.gitkeep temp/processed/.gitkeep temp/failed/.gitkeep
```

- [ ] **Step 5: Start infra services and verify they are healthy**

```bash
docker compose up -d app_postgres phoenix_postgres phoenix
docker compose ps
```

Expected: `app_postgres`, `phoenix_postgres`, and `phoenix` all show `healthy` within 30 seconds.

```bash
# Verify pgvector is available in app_postgres (the extension library is installed)
docker compose exec app_postgres psql -U second_brain -c "SELECT * FROM pg_available_extensions WHERE name = 'vector';"
```

Expected: One row returned with `name = vector`.

```bash
# Verify Phoenix UI is reachable
curl -s -o /dev/null -w "%{http_code}" http://localhost:6006
```

Expected: `200`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml apps/backend/.env.template temp/
git commit -m "feat: add Docker services for postgres, phoenix, and backend"
```

---

### Task 2: Python Project Bootstrap

**Files:**
- Create: `apps/backend/pyproject.toml`
- Create: `apps/backend/Dockerfile`
- Create: `apps/backend/src/second_brain/__init__.py` (and all sub-package stubs)
- Create: `apps/backend/tests/__init__.py` (and all test sub-package stubs)

- [ ] **Step 1: Create `apps/backend/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "second-brain"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlmodel>=0.0.22",
    "alembic>=1.14.0",
    "psycopg2-binary>=2.9.10",
    "pgvector>=0.3.6",
    "pydantic-settings>=2.7.0",
    "langchain-anthropic>=0.3.0",
    "langgraph>=0.2.0",
    "anthropic>=0.40.0",
    "tavily-python>=0.5.0",
    "opentelemetry-sdk>=1.28.0",
    "opentelemetry-exporter-otlp-proto-http>=1.28.0",
    "opentelemetry-instrumentation-fastapi>=0.49b0",
    "arize-phoenix-otel>=0.7.0",
    "presidio-analyzer>=2.2.0",
    "presidio-anonymizer>=2.2.0",
    "spacy>=3.8.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.28.0",
]
eval = [
    "ragas>=0.2.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/second_brain"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]
```

- [ ] **Step 2: Create `apps/backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps: gcc + libpq-dev for psycopg2, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Download spacy English model required by presidio-analyzer for PII detection
RUN python -m spacy download en_core_web_lg

# Copy application source and alembic config
COPY src/ ./src/
COPY alembic.ini .
COPY alembic/ ./alembic/

# Mount point for the temp/ volume
RUN mkdir -p /app/temp/pending-digest-docs /app/temp/processed /app/temp/failed

CMD ["uvicorn", "second_brain.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create all package stub files**

Run from `apps/backend/`:

```bash
mkdir -p src/second_brain/api/routers
mkdir -p src/second_brain/db
mkdir -p src/second_brain/graphs
mkdir -p src/second_brain/nodes
mkdir -p src/second_brain/services
mkdir -p src/second_brain/observability
mkdir -p tests/unit/test_services
mkdir -p tests/integration
mkdir -p eval/dataset

touch src/second_brain/__init__.py
touch src/second_brain/api/__init__.py
touch src/second_brain/api/routers/__init__.py
touch src/second_brain/db/__init__.py
touch src/second_brain/graphs/__init__.py
touch src/second_brain/nodes/__init__.py
touch src/second_brain/services/__init__.py
touch src/second_brain/observability/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/unit/test_services/__init__.py
touch tests/integration/__init__.py
touch eval/dataset/.gitkeep
```

Create `apps/backend/src/second_brain/api/schemas.py` (placeholder for future tickets):

```python
# API request/response schemas — populated in later tickets.
```

- [ ] **Step 4: Install dependencies locally**

```bash
# From apps/backend/
pip install -e ".[dev]"
```

Expected: All packages install without errors.

- [ ] **Step 5: Verify package is importable**

```bash
python -c "import second_brain; print('second_brain OK')"
```

Expected: `second_brain OK`

- [ ] **Step 6: Commit**

```bash
git add apps/backend/
git commit -m "feat: bootstrap Python package structure and all dependencies"
```

---

### Task 3: Config Module and FastAPI Health Check (TDD)

**Files:**
- Create: `apps/backend/tests/conftest.py`
- Create: `apps/backend/tests/test_health.py`
- Create: `apps/backend/src/second_brain/config.py`
- Create: `apps/backend/src/second_brain/main.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/conftest.py`:

```python
import os

# Set env vars before any second_brain module is imported.
# pydantic-settings reads env vars at Settings() instantiation time (module level).
# pytest processes conftest.py before importing test files, so these are set first.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
```

Create `apps/backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from second_brain.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_ok_body():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run to verify tests fail**

```bash
# From apps/backend/
pytest tests/test_health.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'second_brain.main'`

- [ ] **Step 3: Implement `config.py`**

Create `apps/backend/src/second_brain/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://localhost:11434"
    anthropic_api_key: str
    tavily_api_key: str
    phoenix_collector_endpoint: str = "http://localhost:6006/v1/traces"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
```

- [ ] **Step 4: Implement `main.py`**

Create `apps/backend/src/second_brain/main.py`:

```python
from fastapi import FastAPI

from second_brain.config import settings  # noqa: F401 — validates config at startup

app = FastAPI(title="Second Brain", version="0.1.0")


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: Run to verify tests pass**

```bash
# From apps/backend/
pytest tests/test_health.py -v
```

Expected:
```
tests/test_health.py::test_health_returns_200 PASSED
tests/test_health.py::test_health_returns_ok_body PASSED
2 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/config.py \
        apps/backend/src/second_brain/main.py \
        apps/backend/tests/conftest.py \
        apps/backend/tests/test_health.py
git commit -m "feat: add config module and health check endpoint"
```

---

### Task 4: Database Models (TDD)

**Files:**
- Create: `apps/backend/tests/unit/test_models.py`
- Create: `apps/backend/src/second_brain/db/models.py`
- Create: `apps/backend/src/second_brain/db/session.py`

**Important naming note:** `DocumentChunk` uses the Python attribute `chunk_metadata` (mapped to SQL column `metadata`) to avoid shadowing SQLModel/SQLAlchemy's class-level `metadata` attribute. All tickets that access this field in Python must use `.chunk_metadata`.

- [ ] **Step 1: Write the failing model tests**

Create `apps/backend/tests/unit/test_models.py`:

```python
import uuid
from datetime import UTC, datetime

import pytest

from second_brain.db.models import (
    ChatHistory,
    DocumentChunk,
    IngestedDocument,
    LearnedFact,
    ModelCorrection,
)


class TestChatHistory:
    def test_instantiation(self):
        record = ChatHistory(
            session_id="01234567-0123-7000-8000-000000000000",
            thread_data={"messages": []},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert record.session_id == "01234567-0123-7000-8000-000000000000"
        assert record.thread_data == {"messages": []}

    def test_thread_data_defaults_to_empty_dict(self):
        record = ChatHistory(session_id="test-session-id")
        assert record.thread_data == {}


class TestIngestedDocument:
    def test_instantiation(self):
        doc_id = uuid.uuid4()
        record = IngestedDocument(
            id=doc_id,
            filename="notes.md",
            content_hash="d41d8cd98f00b204e9800998ecf8427e",
            status="processed",
            ingested_at=datetime.now(UTC),
        )
        assert record.id == doc_id
        assert record.filename == "notes.md"
        assert record.status == "processed"

    def test_source_url_is_optional(self):
        record = IngestedDocument(
            id=uuid.uuid4(),
            filename="local.md",
            content_hash="abc123",
            status="processed",
            ingested_at=datetime.now(UTC),
        )
        assert record.source_url is None


class TestDocumentChunk:
    def test_instantiation(self):
        record = DocumentChunk(
            id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            content="This chunk discusses Python basics.",
            embedding=[0.1] * 1024,
            chunk_index=0,
            chunk_metadata={"source": "notes.md", "heading_path": "Introduction"},
            created_at=datetime.now(UTC),
        )
        assert record.content == "This chunk discusses Python basics."
        assert len(record.embedding) == 1024
        assert record.chunk_index == 0

    def test_embedding_dimension(self):
        record = DocumentChunk(
            id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            content="text",
            embedding=[0.0] * 1024,
            chunk_index=1,
            created_at=datetime.now(UTC),
        )
        assert len(record.embedding) == 1024

    def test_chunk_metadata_defaults_to_none(self):
        record = DocumentChunk(
            id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            content="text",
            embedding=[0.0] * 1024,
            chunk_index=0,
            created_at=datetime.now(UTC),
        )
        assert record.chunk_metadata is None


class TestLearnedFact:
    def test_instantiation(self):
        record = LearnedFact(
            id=uuid.uuid4(),
            fact="The user prefers Python over Java",
            embedding=[0.2] * 1024,
            source_session="01234567-0123-7000-8000-000000000000",
            confidence=0.9,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert record.fact == "The user prefers Python over Java"
        assert record.confidence == 0.9

    def test_confidence_accepts_float(self):
        record = LearnedFact(
            id=uuid.uuid4(),
            fact="User works at Thoughtworks",
            embedding=[0.0] * 1024,
            source_session="some-session",
            confidence=0.75,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert record.confidence == pytest.approx(0.75)


class TestModelCorrection:
    def test_instantiation(self):
        record = ModelCorrection(
            id=uuid.uuid4(),
            original_answer="Python was created in 1990",
            correction="Python was created in 1991",
            root_cause="Off-by-one year error in training data",
            embedding=[0.3] * 1024,
            source_session="01234567-0123-7000-8000-000000000000",
            created_at=datetime.now(UTC),
        )
        assert record.original_answer == "Python was created in 1990"
        assert record.correction == "Python was created in 1991"
        assert record.root_cause == "Off-by-one year error in training data"

    def test_embedding_encodes_correction_field(self):
        # Embedding is computed from `correction`, not `original_answer`.
        # This test documents that invariant — enforcement is in the persistence node.
        record = ModelCorrection(
            id=uuid.uuid4(),
            original_answer="wrong answer",
            correction="right answer",
            root_cause="factual error",
            embedding=[0.5] * 1024,
            source_session="session-abc",
            created_at=datetime.now(UTC),
        )
        assert len(record.embedding) == 1024
```

- [ ] **Step 2: Run to verify tests fail**

```bash
# From apps/backend/
pytest tests/unit/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'second_brain.db.models'`

- [ ] **Step 3: Implement `db/models.py`**

Create `apps/backend/src/second_brain/db/models.py`:

```python
"""SQLModel table definitions — all 5 tables.

Naming note: DocumentChunk uses `chunk_metadata` as the Python attribute name
(mapped to the `metadata` SQL column via sa_column) to avoid shadowing
SQLModel's class-level `metadata` attribute inherited from SQLAlchemy's
declarative base. All other code must use `.chunk_metadata` in Python.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ChatHistory(SQLModel, table=True):
    """LangGraph session state — keyed by UUID7 string (also the LangGraph thread_id)."""

    __tablename__ = "chat_history"

    session_id: str = Field(primary_key=True)
    thread_data: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))


class IngestedDocument(SQLModel, table=True):
    """Deduplication record for ingested files and URLs."""

    __tablename__ = "ingested_documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    filename: str
    source_url: Optional[str] = Field(default=None)
    content_hash: str  # MD5 of raw file content; used to skip re-ingestion
    status: str  # 'processed' | 'failed'
    ingested_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))


class DocumentChunk(SQLModel, table=True):
    """A single chunk from an ingested document, with embedding for RAG retrieval."""

    __tablename__ = "document_chunks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    doc_id: uuid.UUID = Field(foreign_key="ingested_documents.id")
    content: str  # chunk text with LLM-generated contextual header prepended
    embedding: list[float] = Field(sa_column=Column(Vector(1024), nullable=True))
    chunk_index: int
    # Python attr `chunk_metadata` maps to SQL column `metadata`.
    # Do NOT rename the column — the SQL schema uses `metadata`.
    # Do NOT use `metadata` as the Python attr — it conflicts with SQLAlchemy internals.
    chunk_metadata: Optional[dict] = Field(
        default=None, sa_column=Column("metadata", JSONB, nullable=True)
    )
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))


class LearnedFact(SQLModel, table=True):
    """A user fact extracted from conversation and stored for semantic retrieval."""

    __tablename__ = "learned_facts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    fact: str  # PII-scrubbed fact text
    embedding: list[float] = Field(sa_column=Column(Vector(1024), nullable=True))
    source_session: str = Field(foreign_key="chat_history.session_id")
    confidence: float
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))


class ModelCorrection(SQLModel, table=True):
    """A user correction to a model answer — embedding encodes the `correction` field."""

    __tablename__ = "model_corrections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    original_answer: str
    correction: str
    root_cause: str
    # Embedding encodes `correction` (not `original_answer`) per architecture decision.
    embedding: list[float] = Field(sa_column=Column(Vector(1024), nullable=True))
    source_session: str = Field(foreign_key="chat_history.session_id")
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
```

- [ ] **Step 4: Implement `db/session.py`**

Create `apps/backend/src/second_brain/db/session.py`:

```python
from collections.abc import Generator

from sqlmodel import Session, create_engine

from second_brain.config import settings

engine = create_engine(settings.database_url, echo=False)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLModel session and closes it on exit."""
    with Session(engine) as session:
        yield session
```

- [ ] **Step 5: Run to verify tests pass**

```bash
# From apps/backend/
pytest tests/unit/test_models.py -v
```

Expected:
```
tests/unit/test_models.py::TestChatHistory::test_instantiation PASSED
tests/unit/test_models.py::TestChatHistory::test_thread_data_defaults_to_empty_dict PASSED
tests/unit/test_models.py::TestIngestedDocument::test_instantiation PASSED
tests/unit/test_models.py::TestIngestedDocument::test_source_url_is_optional PASSED
tests/unit/test_models.py::TestDocumentChunk::test_instantiation PASSED
tests/unit/test_models.py::TestDocumentChunk::test_embedding_dimension PASSED
tests/unit/test_models.py::TestDocumentChunk::test_chunk_metadata_defaults_to_none PASSED
tests/unit/test_models.py::TestLearnedFact::test_instantiation PASSED
tests/unit/test_models.py::TestLearnedFact::test_confidence_accepts_float PASSED
tests/unit/test_models.py::TestModelCorrection::test_instantiation PASSED
tests/unit/test_models.py::TestModelCorrection::test_embedding_encodes_correction_field PASSED
11 passed
```

- [ ] **Step 6: Run all unit tests to confirm no regressions**

```bash
# From apps/backend/
pytest tests/test_health.py tests/unit/ -v
```

Expected: All 13 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/second_brain/db/ apps/backend/tests/unit/
git commit -m "feat: add SQLModel table definitions and database session"
```

---

### Task 5: Alembic Setup and First Migration

**Files:**
- Create: `apps/backend/alembic.ini`
- Create: `apps/backend/alembic/__init__.py`
- Create: `apps/backend/alembic/env.py`
- Create: `apps/backend/alembic/versions/__init__.py`
- Create: `apps/backend/alembic/versions/001_initial_schema.py`
- Create: `apps/backend/tests/integration/test_migration.py`

- [ ] **Step 1: Create `apps/backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
# URL is overridden in env.py from the DATABASE_URL environment variable.
# This placeholder allows alembic.ini to parse without errors.
sqlalchemy.url = postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Create `apps/backend/alembic/__init__.py` and versions directory**

```bash
# From apps/backend/
touch alembic/__init__.py
mkdir -p alembic/versions
touch alembic/versions/__init__.py
```

- [ ] **Step 3: Create `apps/backend/alembic/env.py`**

```python
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Add src/ to sys.path so `second_brain` package is importable from here.
# alembic/env.py lives at apps/backend/alembic/env.py;
# parent.parent resolves to apps/backend/, and src/ is one level below.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from second_brain.config import settings  # noqa: E402
import second_brain.db.models  # noqa: F401, E402 — side-effect: registers all table metadata

config = context.config

# Override the alembic.ini URL with the value from the environment
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Create `apps/backend/alembic/versions/001_initial_schema.py`**

```python
"""Initial schema — creates all 5 tables and enables pgvector extension.

Revision ID: 001
Revises:
Create Date: 2026-06-16
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector — must run before creating VECTOR columns
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "chat_history",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("thread_data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
    )

    op.create_table(
        "ingested_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("doc_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["doc_id"], ["ingested_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "learned_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("source_session", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_session"], ["chat_history.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "model_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_answer", sa.Text(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("source_session", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_session"], ["chat_history.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("model_corrections")
    op.drop_table("learned_facts")
    op.drop_table("document_chunks")
    op.drop_table("ingested_documents")
    op.drop_table("chat_history")
    op.execute("DROP EXTENSION IF EXISTS vector")
```

- [ ] **Step 5: Write the migration integration test**

Create `apps/backend/tests/integration/test_migration.py`:

```python
"""Integration test: verifies Alembic migration creates all expected tables.

Requires `app_postgres` to be running via docker compose AND the migration
to have been applied first with `alembic upgrade head`.

Run with:
  DATABASE_URL=postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain \
  pytest tests/integration/test_migration.py -v
"""

import os

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture(scope="module")
def db_engine():
    """Connect to the real Postgres. Skip if DATABASE_URL looks like a test placeholder."""
    url = os.environ.get("DATABASE_URL", "")
    if "test-api-key" in url or (
        "localhost" not in url and "app_postgres" not in url
    ):
        pytest.skip(
            "DATABASE_URL does not point to a real running database — skipping migration test"
        )
    engine = create_engine(url)
    yield engine
    engine.dispose()


def test_all_five_tables_exist(db_engine):
    inspector = inspect(db_engine)
    actual = set(inspector.get_table_names())
    expected = {
        "chat_history",
        "ingested_documents",
        "document_chunks",
        "learned_facts",
        "model_corrections",
    }
    missing = expected - actual
    assert not missing, f"Missing tables after migration: {missing}"


def test_pgvector_extension_is_enabled(db_engine):
    with db_engine.connect() as conn:
        row = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).fetchone()
    assert row is not None, "pgvector extension is not enabled in the database"


def test_document_chunks_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("document_chunks")}
    assert {"id", "doc_id", "content", "embedding", "chunk_index", "metadata", "created_at"}.issubset(columns)


def test_learned_facts_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("learned_facts")}
    assert {"id", "fact", "embedding", "source_session", "confidence", "created_at", "updated_at"}.issubset(columns)


def test_model_corrections_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("model_corrections")}
    assert {"id", "original_answer", "correction", "root_cause", "embedding", "source_session", "created_at"}.issubset(columns)


def test_chat_history_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("chat_history")}
    assert {"session_id", "thread_data", "created_at", "updated_at"}.issubset(columns)


def test_document_chunks_fk_to_ingested_documents(db_engine):
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("document_chunks")
    referred = {fk["referred_table"] for fk in fks}
    assert "ingested_documents" in referred


def test_learned_facts_fk_to_chat_history(db_engine):
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("learned_facts")
    referred = {fk["referred_table"] for fk in fks}
    assert "chat_history" in referred


def test_model_corrections_fk_to_chat_history(db_engine):
    inspector = inspect(db_engine)
    fks = inspector.get_foreign_keys("model_corrections")
    referred = {fk["referred_table"] for fk in fks}
    assert "chat_history" in referred
```

- [ ] **Step 6: Run the migration against the running Postgres container**

```bash
# From apps/backend/ — app_postgres must be running from Task 1
DATABASE_URL="postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain" \
  alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Context impl PostgreSQLImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema — creates all 5 tables and enables pgvector extension.
```

- [ ] **Step 7: Run the integration tests**

```bash
# From apps/backend/
DATABASE_URL="postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain" \
  pytest tests/integration/test_migration.py -v
```

Expected:
```
tests/integration/test_migration.py::test_all_five_tables_exist PASSED
tests/integration/test_migration.py::test_pgvector_extension_is_enabled PASSED
tests/integration/test_migration.py::test_document_chunks_columns PASSED
tests/integration/test_migration.py::test_learned_facts_columns PASSED
tests/integration/test_migration.py::test_model_corrections_columns PASSED
tests/integration/test_migration.py::test_chat_history_columns PASSED
tests/integration/test_migration.py::test_document_chunks_fk_to_ingested_documents PASSED
tests/integration/test_migration.py::test_learned_facts_fk_to_chat_history PASSED
tests/integration/test_migration.py::test_model_corrections_fk_to_chat_history PASSED
9 passed
```

- [ ] **Step 8: Verify no pending migrations remain**

```bash
# From apps/backend/
DATABASE_URL="postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain" \
  alembic check
```

Expected: `No new upgrade operations detected.`

- [ ] **Step 9: Commit**

```bash
git add apps/backend/alembic.ini apps/backend/alembic/ apps/backend/tests/integration/
git commit -m "feat: add Alembic migration for all 5 database tables with pgvector"
```

---

### Task 6: End-to-End Verification

**Files:** None (verification and smoke test only)

- [ ] **Step 1: Build and start all services**

```bash
# From project root
docker compose up -d --build
```

The `backend` service build will take a few minutes (spacy model download is ~500 MB).

- [ ] **Step 2: Confirm all services are running**

```bash
docker compose ps
```

Expected: `app_postgres` (healthy), `phoenix_postgres` (healthy), `phoenix` (running), `backend` (running). The `ollama-checker` service should show `exited (0)`.

- [ ] **Step 3: Verify health endpoint responds**

```bash
curl -s http://localhost:8000/health
```

Expected:
```json
{"status":"ok"}
```

- [ ] **Step 4: Verify all 5 tables exist in the containerised database**

```bash
docker compose exec app_postgres psql -U second_brain -c "\dt"
```

Expected (all 5 tables listed):
```
            List of relations
 Schema |        Name         | Type  |    Owner
--------+---------------------+-------+--------------
 public | chat_history        | table | second_brain
 public | document_chunks     | table | second_brain
 public | ingested_documents  | table | second_brain
 public | learned_facts       | table | second_brain
 public | model_corrections   | table | second_brain
(5 rows)
```

- [ ] **Step 5: Verify pgvector extension**

```bash
docker compose exec app_postgres psql -U second_brain -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```

Expected: One row with `extname = vector`.

- [ ] **Step 6: Run all unit tests**

```bash
# From apps/backend/
pytest tests/test_health.py tests/unit/ -v
```

Expected: All 13 tests PASS (2 health + 11 model).

- [ ] **Step 7: Confirm done criteria**

All of the following must be true before this ticket is closed:

- `docker compose up` starts all services without errors
- All 5 DB tables exist with correct schema (verified in Step 4)
- `GET /health` returns `{"status": "ok"}` with HTTP 200 (Step 3)
- `alembic upgrade head` runs cleanly inside the backend container (Steps 6-8 of Task 5)
- All unit tests pass (Step 6)

---

## Self-Review

**Spec coverage:**
- Docker infrastructure with correct network isolation — Task 1
- `.env.template` expanded with all env vars — Task 1, Step 2
- `pyproject.toml` with all named dependencies — Task 2, Step 1
- `Dockerfile` for backend service — Task 2, Step 2
- `config.py` with `Settings` matching spec exactly — Task 3, Step 3
- FastAPI skeleton with `/health` endpoint — Task 3, Step 4
- All 5 SQLModel models with correct field types and FKs — Task 4, Step 3
- `db/session.py` with `get_session` dependency — Task 4, Step 4
- Alembic `alembic.ini` and `env.py` — Task 5, Steps 1–3
- First migration with all 5 tables + pgvector extension — Task 5, Step 4
- `temp/` folder structure — Task 1, Step 4
- Health check unit tests — Task 3
- Model instantiation unit tests — Task 4
- Migration integration tests — Task 5, Step 5
- End-to-end verification — Task 6

**Type consistency:**
- `ChatHistory.session_id: str` — UUID7 stored as string. FK target for `source_session` in `LearnedFact` and `ModelCorrection`. Consistent in models, migration, and tests.
- `DocumentChunk.chunk_metadata` (Python) → `metadata` (SQL column) — noted in models.py docstring, tests use `chunk_metadata`, migration creates column named `metadata`. Integration test checks for column named `metadata`. **Future tickets: use `.chunk_metadata` in Python, `metadata` in raw SQL.**
- All embedding fields: `list[float]` with `Vector(1024)` — consistent across `DocumentChunk`, `LearnedFact`, `ModelCorrection` in models.py, migration, and tests.
- `ModelCorrection.embedding` encodes the `correction` field (not `original_answer`) — documented in model docstring and test.
- Foreign keys: `document_chunks.doc_id → ingested_documents.id` (UUID), `learned_facts.source_session → chat_history.session_id` (string), `model_corrections.source_session → chat_history.session_id` (string).

**Known divergence from spec field names:**
- `DocumentChunk.metadata` is implemented as `DocumentChunk.chunk_metadata` in Python due to a conflict with SQLModel/SQLAlchemy's class-level `metadata` attribute. The SQL column name is still `metadata` as specified. This is the only divergence; all other field names match the spec exactly.
