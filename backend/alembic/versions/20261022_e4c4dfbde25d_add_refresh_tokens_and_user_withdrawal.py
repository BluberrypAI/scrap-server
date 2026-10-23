"""add refresh tokens and user withdrawal

Revision ID: e4c4dfbde25d
Revises: 5818173979f8
Create Date: 2026-10-22 18:56:57.195615
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4c4dfbde25d"
down_revision: str | None = "5818173979f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.add_column("users", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("deletion_scheduled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_users_deletion_scheduled_at"), "users", ["deletion_scheduled_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_deletion_scheduled_at"), table_name="users")
    op.drop_column("users", "deletion_scheduled_at")
    op.drop_column("users", "withdrawn_at")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
