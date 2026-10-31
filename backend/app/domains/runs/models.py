import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    # 엔진이 결과를 돌려줌
    COMPLETED = "completed"
    # 결과는 있으나 조회 한도 때문에 전체 후보를 다 읽지 못함
    PARTIAL = "partial"
    FAILED = "failed"


# 결과 조회 API가 읽을 수 있는 상태
FINISHED_WITH_RESULT = (RunStatus.COMPLETED, RunStatus.PARTIAL)
# 같은 검토에서 새 실행을 막는 상태
IN_PROGRESS = (RunStatus.QUEUED, RunStatus.RUNNING)


class RunErrorCode(StrEnum):
    """실행 실패 원인. HTTP 오류가 아니라 실행 레코드에 남는 값임."""

    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    ENGINE_TIMEOUT = "ENGINE_TIMEOUT"
    ENGINE_REJECTED_INPUT = "ENGINE_REJECTED_INPUT"
    GRAPH_VERSION_CHANGED = "GRAPH_VERSION_CHANGED"
    ENGINE_CONTRACT_MISMATCH = "ENGINE_CONTRACT_MISMATCH"
    WORKER_INTERRUPTED = "WORKER_INTERRUPTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class Run(Base, TimestampMixin):
    """검토 실행 1회. 실행에 쓴 입력과 버전을 고정하고 엔진 응답 원문을 보관함."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    # 재실행이면 원래 실행 (review-risks-supplements)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    rerun_from_stage: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]
        )
    )
    # [{"stage", "status", "reason"}]. 단계 목록은 runs/stages.py
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    # 엔진 라우터 판정 (PASS, REVISE, REVIEW). 엔진이 돌려준 값만 넣음
    router_state: Mapped[str | None] = mapped_column(String(20))
    # 입력·기업 정보·근거·그래프 버전 (NFR-3 추적성)
    pinned_versions: Mapped[dict[str, Any]] = mapped_column(JSON)
    # 엔진에 보낸 lot (확인된 값만)
    lot: Mapped[dict[str, Any]] = mapped_column(JSON)
    # 엔진 응답 원문 (candidate-research-v1). 결과 조회 API는 이 값만 읽음
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[RunErrorCode | None] = mapped_column(
        Enum(
            RunErrorCode,
            native_enum=False,
            length=40,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
