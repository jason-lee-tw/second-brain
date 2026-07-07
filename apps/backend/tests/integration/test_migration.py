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
  """Connect to the real Postgres. Skip if DATABASE_URL is a test placeholder."""
  url = os.environ.get("DATABASE_URL", "")
  if "test-api-key" in url or ("localhost" not in url and "app_postgres" not in url):
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
  assert {
    "id",
    "doc_id",
    "content",
    "embedding",
    "chunk_index",
    "metadata",
    "created_at",
  }.issubset(columns)


def test_learned_facts_columns(db_engine):
  inspector = inspect(db_engine)
  columns = {col["name"] for col in inspector.get_columns("learned_facts")}
  assert {
    "id",
    "fact",
    "embedding",
    "source_session",
    "confidence",
    "created_at",
    "updated_at",
  }.issubset(columns)


def test_model_corrections_columns(db_engine):
  inspector = inspect(db_engine)
  columns = {col["name"] for col in inspector.get_columns("model_corrections")}
  assert {
    "id",
    "original_answer",
    "correction",
    "root_cause",
    "embedding",
    "source_session",
    "created_at",
  }.issubset(columns)


def test_chat_history_columns(db_engine):
  inspector = inspect(db_engine)
  columns = {col["name"] for col in inspector.get_columns("chat_history")}
  assert {"session_id", "thread_data", "created_at", "updated_at"}.issubset(columns)


def test_ingested_documents_columns(db_engine):
  inspector = inspect(db_engine)
  columns = {col["name"] for col in inspector.get_columns("ingested_documents")}
  assert {
    "id",
    "filename",
    "source_url",
    "content_hash",
    "status",
    "ingested_at",
  }.issubset(columns)


def test_document_chunks_fk_to_ingested_documents(db_engine):
  inspector = inspect(db_engine)
  fks = inspector.get_foreign_keys("document_chunks")
  referred = {fk["referred_table"] for fk in fks}
  assert "ingested_documents" in referred


def test_learned_facts_no_fk_to_chat_history(db_engine):
  """Migration 002 dropped this FK — chat_history is never written by the app."""
  inspector = inspect(db_engine)
  fks = inspector.get_foreign_keys("learned_facts")
  referred = {fk["referred_table"] for fk in fks}
  assert "chat_history" not in referred


def test_model_corrections_no_fk_to_chat_history(db_engine):
  """Migration 002 dropped this FK — chat_history is never written by the app."""
  inspector = inspect(db_engine)
  fks = inspector.get_foreign_keys("model_corrections")
  referred = {fk["referred_table"] for fk in fks}
  assert "chat_history" not in referred
