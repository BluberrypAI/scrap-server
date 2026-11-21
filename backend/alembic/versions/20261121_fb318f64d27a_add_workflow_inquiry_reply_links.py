"""add workflow inquiry reply links

Revision ID: fb318f64d27a
Revises: c4d8e1f27a63
Create Date: 2026-11-21 17:01:55.235121
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb318f64d27a"
down_revision: str | None = "c4d8e1f27a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_inquiry_reply_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("capability_key", sa.String(length=100), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inquiry", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_workflow_inquiry_reply_links_company_id_companies"),
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["workflow_lots.id"],
            name=op.f("fk_workflow_inquiry_reply_links_lot_id_workflow_lots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_inquiry_reply_links")),
        sa.UniqueConstraint(
            "lot_id", "capability_key", name=op.f("uq_workflow_inquiry_reply_links_lot_id")
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_workflow_inquiry_reply_links_token_hash")),
    )
    op.add_column(
        "workflow_inquiry_replies",
        sa.Column("source", sa.String(length=16), server_default="sender", nullable=False),
    )
    op.add_column(
        "workflow_inquiry_replies", sa.Column("availability", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "workflow_inquiry_replies", sa.Column("contact_name", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "workflow_inquiry_replies", sa.Column("contact_info", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workflow_inquiry_replies", "contact_info")
    op.drop_column("workflow_inquiry_replies", "contact_name")
    op.drop_column("workflow_inquiry_replies", "availability")
    op.drop_column("workflow_inquiry_replies", "source")
    op.drop_table("workflow_inquiry_reply_links")
