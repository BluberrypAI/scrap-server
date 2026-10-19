"""create users companies waste profiles

Revision ID: 5818173979f8
Revises:
Create Date: 2026-10-15 18:25:39.966995
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5818173979f8"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=False),
        sa.Column("manager_name", sa.String(length=100), nullable=False),
        sa.Column("manager_phone", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_companies_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("owner_user_id", name=op.f("uq_companies_owner_user_id")),
    )
    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_social_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_accounts")),
        sa.UniqueConstraint(
            "provider", "provider_subject", name=op.f("uq_social_accounts_provider")
        ),
    )
    op.create_index(
        op.f("ix_social_accounts_user_id"), "social_accounts", ["user_id"], unique=False
    )
    op.create_table(
        "waste_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column(
            "generation_cycle",
            sa.Enum(
                "daily",
                "weekly",
                "monthly",
                "irregular",
                name="generationcycle",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("expected_monthly_volume_kg", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_waste_profiles_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waste_profiles")),
    )
    op.create_index(
        op.f("ix_waste_profiles_company_id"), "waste_profiles", ["company_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_waste_profiles_company_id"), table_name="waste_profiles")
    op.drop_table("waste_profiles")
    op.drop_index(op.f("ix_social_accounts_user_id"), table_name="social_accounts")
    op.drop_table("social_accounts")
    op.drop_table("companies")
    op.drop_table("users")
