"""company profile fields, version and history

Revision ID: 31ad7bc77087
Revises: e4c4dfbde25d
Create Date: 2026-10-23 19:10:52.641706

Renames columns to the API spec names (CORP-002) instead of drop+add, so data is kept.
business_registration_no and representative_name are NOT NULL without a default: this
assumes no companies exist yet (pre-release). See docs/specs/company-onboarding.md 5장.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "31ad7bc77087"
down_revision: str | None = "e4c4dfbde25d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = [
    ("name", "company_name"),
    ("address", "head_office_address"),
    ("manager_name", "contact_name"),
    ("manager_phone", "contact_phone"),
]


def upgrade() -> None:
    # batch_alter_table so the same migration runs on SQLite (no ALTER COLUMN) and PostgreSQL.
    with op.batch_alter_table("companies") as batch:
        for old, new in RENAMES:
            batch.alter_column(old, new_column_name=new)
        batch.add_column(
            sa.Column("business_registration_no", sa.String(length=10), nullable=False)
        )
        batch.add_column(sa.Column("representative_name", sa.String(length=100), nullable=False))
        batch.add_column(sa.Column("contact_email", sa.String(length=320), nullable=True))
        batch.add_column(
            sa.Column("profile_version", sa.Integer(), server_default="1", nullable=False)
        )

    op.create_table(
        "company_profile_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_company_profile_history_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_profile_history")),
        sa.UniqueConstraint(
            "company_id", "profile_version", name=op.f("uq_company_profile_history_company_id")
        ),
    )
    op.create_index(
        op.f("ix_company_profile_history_company_id"),
        "company_profile_history",
        ["company_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_company_profile_history_company_id"), table_name="company_profile_history"
    )
    op.drop_table("company_profile_history")

    with op.batch_alter_table("companies") as batch:
        batch.drop_column("profile_version")
        batch.drop_column("contact_email")
        batch.drop_column("representative_name")
        batch.drop_column("business_registration_no")
        for old, new in RENAMES:
            batch.alter_column(new, new_column_name=old)
