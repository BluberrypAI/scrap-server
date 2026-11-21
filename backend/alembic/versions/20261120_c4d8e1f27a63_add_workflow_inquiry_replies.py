"""add workflow inquiry replies

Revision ID: c4d8e1f27a63
Revises: ab770188e3f0
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e1f27a63"
down_revision: str | None = "ab770188e3f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_inquiry_replies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("capability_key", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("file_name", sa.String(length=200), nullable=True),
        sa.Column("mime", sa.String(length=100), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_workflow_inquiry_replies_company_id_companies"),
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["workflow_lots.id"],
            name=op.f("fk_workflow_inquiry_replies_lot_id_workflow_lots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_inquiry_replies")),
    )
    op.create_index(
        op.f("ix_workflow_inquiry_replies_lot_id"), "workflow_inquiry_replies", ["lot_id"]
    )
    op.create_index(
        op.f("ix_workflow_inquiry_replies_capability_key"),
        "workflow_inquiry_replies",
        ["capability_key"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_inquiry_replies_capability_key"), table_name="workflow_inquiry_replies"
    )
    op.drop_index(op.f("ix_workflow_inquiry_replies_lot_id"), table_name="workflow_inquiry_replies")
    op.drop_table("workflow_inquiry_replies")
