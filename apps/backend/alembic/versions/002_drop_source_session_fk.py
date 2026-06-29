"""Drop FK from learned_facts/model_corrections source_session to chat_history.

chat_history is never written by the application (LangGraph uses its own
checkpoint tables). source_session is audit metadata only — no referential
integrity needed.

Revision ID: 002
Revises: 001
Create Date: 2026-06-26
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "learned_facts_source_session_fkey", "learned_facts", type_="foreignkey"
    )
    op.drop_constraint(
        "model_corrections_source_session_fkey", "model_corrections", type_="foreignkey"
    )


def downgrade() -> None:
    op.create_foreign_key(
        "learned_facts_source_session_fkey",
        "learned_facts",
        "chat_history",
        ["source_session"],
        ["session_id"],
    )
    op.create_foreign_key(
        "model_corrections_source_session_fkey",
        "model_corrections",
        "chat_history",
        ["source_session"],
        ["session_id"],
    )
