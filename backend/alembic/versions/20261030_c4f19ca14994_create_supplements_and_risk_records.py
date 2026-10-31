"""create supplements and risk records

Revision ID: c4f19ca14994
Revises: cdb956862cec
Create Date: 2026-10-30 19:40:23.696995

supplements: 추가 자료, risk_step_decisions: 리스크 단계 결정, risk_evidence: 리스크 증빙 연결.
docs/specs/review-risks-supplements.md 5장.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f19ca14994"
down_revision: str | None = "cdb956862cec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "inspection_result",
                "facility_response",
                "quote",
                "specification",
                name="supplementtype",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("applied_quantity_kg", sa.Float(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "verification_status",
            sa.Enum(
                "verified", "unverified", name="verificationstatus", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column(
            "applicability",
            sa.Enum("matched", "mismatch", name="applicability", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("mismatch_reason", sa.String(length=300), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_supplements_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplements")),
    )
    op.create_index(op.f("ix_supplements_review_id"), "supplements", ["review_id"], unique=False)
    op.create_table(
        "risk_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.String(length=200), nullable=False),
        sa.Column("risk_id", sa.String(length=300), nullable=False),
        sa.Column("supplement_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_risk_evidence_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_risk_evidence_run_id_runs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supplement_id"],
            ["supplements.id"],
            name=op.f("fk_risk_evidence_supplement_id_supplements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_evidence")),
    )
    op.create_index(op.f("ix_risk_evidence_run_id"), "risk_evidence", ["run_id"], unique=False)
    op.create_table(
        "risk_step_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.String(length=200), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "confirm", "request_evidence", "hold", name="decision", native_enum=False, length=30
            ),
            nullable=False,
        ),
        sa.Column(
            "proceed_option",
            sa.Enum(
                "hold_and_proceed", "exclude", name="proceedoption", native_enum=False, length=30
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_risk_step_decisions_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_step_decisions")),
    )
    op.create_index(
        op.f("ix_risk_step_decisions_run_id"), "risk_step_decisions", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_risk_step_decisions_run_id"), table_name="risk_step_decisions")
    op.drop_table("risk_step_decisions")
    op.drop_index(op.f("ix_risk_evidence_run_id"), table_name="risk_evidence")
    op.drop_table("risk_evidence")
    op.drop_index(op.f("ix_supplements_review_id"), table_name="supplements")
    op.drop_table("supplements")
