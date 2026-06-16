"""Initial schema — creates all 5 tables and enables pgvector extension.

Revision ID: 001
Revises:
Create Date: 2026-06-17
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector — must run before creating VECTOR columns
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # DateTime() (no timezone) matches SQLModel's default mapping for
    # plain Optional[datetime].
    # DateTime(timezone=True) is used only for fields with explicit
    # sa_column=Column(DateTime(timezone=True)).
    # String() (AutoString/VARCHAR) matches SQLModel's default mapping for
    # plain str fields.
    op.create_table(
        "chat_history",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("thread_data", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
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
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("doc_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["doc_id"], ["ingested_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "learned_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact", sa.String(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("source_session", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_session"], ["chat_history.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "model_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_answer", sa.String(), nullable=False),
        sa.Column("correction", sa.String(), nullable=False),
        sa.Column("root_cause", sa.String(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("source_session", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_session"], ["chat_history.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # HNSW indexes for cosine similarity search on embedding columns
    op.execute(
        "CREATE INDEX document_chunks_embedding_idx "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX learned_facts_embedding_idx "
        "ON learned_facts USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX model_corrections_embedding_idx "
        "ON model_corrections USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS model_corrections_embedding_idx")
    op.execute("DROP INDEX IF EXISTS learned_facts_embedding_idx")
    op.execute("DROP INDEX IF EXISTS document_chunks_embedding_idx")
    op.drop_table("model_corrections")
    op.drop_table("learned_facts")
    op.drop_table("document_chunks")
    op.drop_table("ingested_documents")
    op.drop_table("chat_history")
    op.execute("DROP EXTENSION IF EXISTS vector")
