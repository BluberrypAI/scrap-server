"""create documents and values

Revision ID: 7028210f7779
Revises: f14d7d65b9cf
Create Date: 2026-10-30 19:15:35.096864

documents: 검토에 올린 증빙 문서, document_values: 추출된 측정값 후보.
docs/specs/review-documents.md 5장.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7028210f7779"
down_revision: str | None = "f14d7d65b9cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "doc_type",
            sa.Enum("test_report", "other", name="documenttype", native_enum=False, length=30),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "extracting",
                "extracted",
                "failed",
                name="documentstatus",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("file_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_documents_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_review_id"), "documents", ["review_id"], unique=False)
    op.create_table(
        "document_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("source_location", sa.String(length=300), nullable=True),
        sa.Column("basis", sa.String(length=200), nullable=True),
        sa.Column(
            "verification_status",
            sa.Enum(
                "verified", "unverified", name="verificationstatus", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_values_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_values")),
    )
    op.create_index(
        op.f("ix_document_values_document_id"), "document_values", ["document_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_values_document_id"), table_name="document_values")
    op.drop_table("document_values")
    op.drop_index(op.f("ix_documents_review_id"), table_name="documents")
    op.drop_table("documents")
