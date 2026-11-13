import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WasteStatus(StrEnum):
    """폐기물 건 진행 상태 (프론트 6단계)."""

    DIAGNOSING = "diagnosing"  # 문진 중
    PENDING_ANALYSIS = "pending_analysis"  # 분석 대기
    CANDIDATES = "candidates"  # 후보 제시
    CONFIRMED = "confirmed"  # 확정
    IN_PROGRESS = "in_progress"  # 처리 진행
    COMPLETED = "completed"  # 완료


def _values(enum: type[StrEnum]) -> list[str]:
    # DB에는 이름(DIAGNOSING)이 아니라 값(diagnosing)을 저장함
    return [member.value for member in enum]


class CheckRole(StrEnum):
    """QR 현장 확인을 한 사람의 역할."""

    DRIVER = "driver"  # 운반 시작 (운전자)
    RECIPIENT = "recipient"  # 입고 (수령자)


class Waste(Base, TimestampMixin):
    """폐기물 건 하나. 프론트 폐기물 목록의 한 줄이고, QR과 처리 경로가 여기에 붙음."""

    __tablename__ = "wastes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # 품목명 (예: 폐합성수지)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[WasteStatus] = mapped_column(
        Enum(WasteStatus, native_enum=False, length=32, values_callable=_values),
        default=WasteStatus.DIAGNOSING,
        server_default=WasteStatus.DIAGNOSING.value,
    )
    # QR: 토큰 원문은 저장하지 않고 해시만 둠
    qr_token_hash: Mapped[str | None] = mapped_column(String(128))
    qr_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qr_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 확정 분류 결과 (문진 엔진 확정 후 복사). 확정 전에는 비어 있음
    waste_code: Mapped[str | None] = mapped_column(String(20))
    code_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50))
    # 일반·지정 구분
    waste_type: Mapped[str | None] = mapped_column(String(50))
    # {code, name, category}
    r_type: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 근거 조문 목록
    clause_refs: Mapped[list[Any] | None] = mapped_column(JSON)
    law_version_id: Mapped[str | None] = mapped_column(String(100))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 총 처리량 (결과지)
    quantity_value: Mapped[float | None] = mapped_column(Float)
    quantity_unit: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 결과지 공유 링크
    share_token_hash: Mapped[str | None] = mapped_column(String(128))
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouteStep(Base, TimestampMixin):
    """폐기물 건의 처리 경로 한 단계. seq 순서대로 진행함."""

    __tablename__ = "route_steps"
    __table_args__ = (
        UniqueConstraint("waste_id", "seq"),
        # qr_field_checks의 복합 FK (route_step_id, waste_id) 대상
        UniqueConstraint("id", "waste_id", name="uq_route_steps_id_waste_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    waste_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wastes.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    # 단계 구분 (배출, 수집·운반, 중간처리, 최종 재활용)
    stage: Mapped[str] = mapped_column(String(50))
    process: Mapped[str | None] = mapped_column(String(200))
    output: Mapped[str | None] = mapped_column(String(200))
    # recycling, manufacturing
    kind: Mapped[str | None] = mapped_column(String(50))
    facility_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("facilities.id", ondelete="SET NULL"), index=True
    )
    # 시설 정보가 바뀌어도 당시 이름을 남김
    facility_name: Mapped[str | None] = mapped_column(String(200))
    # {code, name, category}
    r_type: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    method: Mapped[str | None] = mapped_column(String(100))
    # 인계, 처리중, 확인, 완료
    status: Mapped[str | None] = mapped_column(String(32))
    planned_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    manifest_no: Mapped[str | None] = mapped_column(String(100))


class QrFieldCheck(Base):
    """QR을 찍고 남긴 현장 확인 기록.

    route_step_id는 비울 수 있음. 채우면 (route_step_id, waste_id) 복합 FK로
    같은 폐기물의 단계만 가리킬 수 있고, 한 단계에서 같은 역할은 한 번만 확인함
    (중복 시 409 STEP_ALREADY_CHECKED).
    """

    __tablename__ = "qr_field_checks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["route_step_id", "waste_id"],
            ["route_steps.id", "route_steps.waste_id"],
            name="fk_qr_field_checks_route_step_waste",
        ),
        Index(
            "uq_qr_field_checks_route_step_id_role",
            "route_step_id",
            "role",
            unique=True,
            postgresql_where=text("route_step_id IS NOT NULL"),
            sqlite_where=text("route_step_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    waste_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wastes.id", ondelete="CASCADE"), index=True
    )
    route_step_id: Mapped[uuid.UUID | None] = mapped_column()
    role: Mapped[CheckRole] = mapped_column(
        Enum(CheckRole, native_enum=False, length=16, values_callable=_values)
    )
    actor_name: Mapped[str] = mapped_column(String(80))
    # 서버 시각
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WasteCompletionSnapshot(Base):
    """폐기물 처리 완료 시점의 기업·사업장 정보. 폐기물 1건당 0..1개, 수정 불가.

    완료 뒤 기업 정보가 바뀌어도 결과지에는 완료 당시 값이 나오게 함.
    """

    __tablename__ = "waste_completion_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # unique: 폐기물 1건당 최대 1개
    waste_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wastes.id", ondelete="CASCADE"), unique=True
    )
    company_name: Mapped[str] = mapped_column(String(200))
    site_name: Mapped[str] = mapped_column(String(200))
    site_address: Mapped[str] = mapped_column(String(500))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImmutableRowError(Exception):
    """수정 불가 테이블의 행을 고치려 할 때."""


@event.listens_for(WasteCompletionSnapshot, "before_update")
def _block_snapshot_update(mapper, connection, target) -> None:  # noqa: ANN001
    # DB에서는 PostgreSQL 트리거가 한 번 더 막음 (마이그레이션 참고)
    raise ImmutableRowError("waste_completion_snapshots 행은 수정할 수 없음")
