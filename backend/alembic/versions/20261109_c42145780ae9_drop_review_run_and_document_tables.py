"""drop review run and document tables

검토·실행·문서·결과·리스크·보완 자료 기능을 없애면서 관련 테이블을 지움 (db-schema-simplify).
downgrade는 빈 테이블만 다시 만들고 지운 데이터는 되돌리지 않음.

Revision ID: c42145780ae9
Revises: b78e23675ea5
Create Date: 2026-11-09 01:05:35.082426
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c42145780ae9"
down_revision: str | None = "b78e23675ea5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # FK를 가진 테이블부터 지움
    op.drop_index(op.f("ix_risk_evidence_run_id"), table_name="risk_evidence")
    op.drop_table("risk_evidence")
    op.drop_index(op.f("ix_risk_step_decisions_run_id"), table_name="risk_step_decisions")
    op.drop_table("risk_step_decisions")
    op.drop_index(op.f("ix_supplements_review_id"), table_name="supplements")
    op.drop_table("supplements")
    op.drop_index(op.f("ix_document_values_document_id"), table_name="document_values")
    op.drop_table("document_values")
    op.drop_index(op.f("ix_runs_review_id"), table_name="runs")
    op.drop_table("runs")
    op.drop_index(op.f("ix_documents_review_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_reviews_company_id"), table_name="reviews")
    op.drop_table("reviews")


def downgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("free_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
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
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
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
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("rerun_from_stage", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("router_state", sa.String(length=20), nullable=True),
        sa.Column("pinned_versions", sa.JSON(), nullable=False),
        sa.Column("lot", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["runs.id"],
            name=op.f("fk_runs_parent_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_runs_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_review_id"), "runs", ["review_id"], unique=False)
    op.create_table(
        "document_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("source_location", sa.String(length=300), nullable=True),
        sa.Column("basis", sa.String(length=200), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
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
    op.create_table(
        "supplements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("applied_quantity_kg", sa.Float(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("applicability", sa.String(length=20), nullable=False),
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
        "risk_step_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.String(length=200), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("proceed_option", sa.String(length=30), nullable=True),
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
