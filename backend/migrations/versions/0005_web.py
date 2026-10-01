"""web_search_logs + kolom sitasi web (Fase 7 — Web Fallback)

Revision ID: 0005_web
Revises: 0004_chats
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_web"
down_revision: str | None = "0004_chats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_search_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False, server_default=sa.text("'none'")),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("log_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_web_search_logs_workspace_id", "web_search_logs", ["workspace_id"])
    op.create_index("ix_web_search_logs_created_at", "web_search_logs", ["created_at"])

    # Fase 7: sitasi web tidak punya chunk/file → nullable
    op.alter_column("citations", "chunk_id", existing_type=sa.String(36), nullable=True)
    op.alter_column("citations", "file_id", existing_type=sa.String(36), nullable=True)
    op.add_column(
        "citations",
        sa.Column(
            "source_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'internal'"),
        ),
    )
    op.add_column("citations", sa.Column("url", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("citations", "url")
    op.drop_column("citations", "source_type")
    op.alter_column("citations", "file_id", existing_type=sa.String(36), nullable=False)
    op.alter_column("citations", "chunk_id", existing_type=sa.String(36), nullable=False)
    op.drop_table("web_search_logs")
