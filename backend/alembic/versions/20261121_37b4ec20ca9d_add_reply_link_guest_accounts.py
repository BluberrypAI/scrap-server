"""Add guest companies for inquiry reply links.

Revision ID: 37b4ec20ca9d
Revises: fb318f64d27a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "37b4ec20ca9d"
down_revision: str | None = "fb318f64d27a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUEST_COMPANY_FK = "fk_workflow_inquiry_reply_links_guest_company_id_companies"
GUEST_COMPANY_UQ = "uq_workflow_inquiry_reply_links_guest_company_id"


def upgrade() -> None:
    op.add_column(
        "companies", sa.Column("guest", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    with op.batch_alter_table("workflow_inquiry_reply_links") as batch:
        batch.add_column(sa.Column("guest_company_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(GUEST_COMPANY_FK, "companies", ["guest_company_id"], ["id"])
        batch.create_unique_constraint(GUEST_COMPANY_UQ, ["guest_company_id"])


def downgrade() -> None:
    with op.batch_alter_table("workflow_inquiry_reply_links") as batch:
        batch.drop_constraint(GUEST_COMPANY_UQ, type_="unique")
        batch.drop_constraint(GUEST_COMPANY_FK, type_="foreignkey")
        batch.drop_column("guest_company_id")
    op.drop_column("companies", "guest")
