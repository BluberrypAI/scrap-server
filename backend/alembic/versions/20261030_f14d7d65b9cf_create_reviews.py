"""create reviews

Revision ID: f14d7d65b9cf
Revises: 31ad7bc77087
Create Date: 2026-10-30 19:08:49.586050

reviews: 검토 1건 (자연어 원문, 기업 기본값 스냅샷, 입력 객체). docs/specs/review-intake.md 5장.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f14d7d65b9cf"
down_revision: str | None = "31ad7bc77087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("free_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "intake_pending", "intake_ready", name="reviewstatus", native_enum=False, length=30
            ),
            nullable=False,
        ),
        sa.Column("company_profile_version", sa.Integer(), nullable=False),
        sa.Column("company_snapshot", sa.JSON(), nullable=False),
        sa.Column("intake", sa.JSON(), nullable=False),
        sa.Column("intake_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_reviews_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index(op.f("ix_reviews_company_id"), "reviews", ["company_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reviews_company_id"), table_name="reviews")
    op.drop_table("reviews")
