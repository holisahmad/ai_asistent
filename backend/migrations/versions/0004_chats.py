"""chats, messages, citations (Fase 6 — Retrieval & RAG)

Revision ID: 0004_chats
Revises: 0003_documents
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_chats"
down_revision: str | None = "0003_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default=sa.text("'Chat'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_chats_workspace_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_chats_user_id", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_chats_workspace_id", "chats", ["workspace_id"])
    op.create_index("ix_chats_user_id", "chats", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer_kind", sa.String(20), nullable=True),
        sa.Column("answer_meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_messages_chat_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"])

    op.create_table(
        "citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("file_id", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("locator_type", sa.String(20), nullable=False),
        sa.Column("locator_start", sa.Integer(), nullable=False),
        sa.Column("locator_end", sa.Integer(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name="fk_citations_message_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_citations_message_id", "citations", ["message_id"])


def downgrade() -> None:
    op.drop_table("citations")
    op.drop_table("messages")
    op.drop_table("chats")
