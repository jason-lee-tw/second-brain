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
from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ChatHistory(SQLModel, table=True):
    """LangGraph session state — UUID7 string is also the LangGraph thread_id."""

    __tablename__ = "chat_history"

    session_id: str = Field(primary_key=True)
    thread_data: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            default=func.now(),
            onupdate=func.now(),
            nullable=True,
        ),
    )


class IngestedDocument(SQLModel, table=True):
    """Deduplication record for ingested files and URLs."""

    __tablename__ = "ingested_documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    filename: str
    source_url: Optional[str] = Field(default=None)
    content_hash: str = Field(
        unique=True
    )  # MD5 of raw file content; used to skip re-ingestion
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
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            default=func.now(),
            onupdate=func.now(),
            nullable=True,
        ),
    )


class ModelCorrection(SQLModel, table=True):
    """A user correction to a model answer; embedding encodes the `correction` field."""

    __tablename__ = "model_corrections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    original_answer: str
    correction: str
    root_cause: str
    # Embedding encodes `correction` (not `original_answer`) per architecture decision.
    embedding: list[float] = Field(sa_column=Column(Vector(1024), nullable=True))
    source_session: str = Field(foreign_key="chat_history.session_id")
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
