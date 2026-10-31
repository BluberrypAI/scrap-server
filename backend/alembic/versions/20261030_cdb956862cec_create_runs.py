"""create runs

Revision ID: cdb956862cec
Revises: 7028210f7779
Create Date: 2026-10-30 19:24:05.033169

runs: 검토 실행 1회 (고정한 입력·버전, 단계 상태, 엔진 응답 원문). docs/specs/review-runs.md 5장.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cdb956862cec"
down_revision: str | None = "7028210f7779"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("rerun_from_stage", sa.String(length=30), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "partial",
                "failed",
                name="runstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("router_state", sa.String(length=20), nullable=True),
        sa.Column("pinned_versions", sa.JSON(), nullable=False),
        sa.Column("lot", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "error_code",
            sa.Enum(
                "ENGINE_UNAVAILABLE",
                "ENGINE_TIMEOUT",
                "ENGINE_REJECTED_INPUT",
                "GRAPH_VERSION_CHANGED",
                "ENGINE_CONTRACT_MISMATCH",
                "WORKER_INTERRUPTED",
                "INTERNAL_ERROR",
                name="runerrorcode",
                native_enum=False,
                length=40,
            ),
            nullable=True,
        ),
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


def downgrade() -> None:
    op.drop_index(op.f("ix_runs_review_id"), table_name="runs")
    op.drop_table("runs")
