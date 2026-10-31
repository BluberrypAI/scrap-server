import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ReviewStatus(StrEnum):
    # 필수 입력이 비어 있어 실행할 수 없음
    INTAKE_PENDING = "intake_pending"
    # 필수 입력이 모두 확인되어 실행할 수 있음
    INTAKE_READY = "intake_ready"


class Review(Base, TimestampMixin):
    """검토 1건. 자연어 원문, 생성 시점의 기업 기본값 스냅샷, 입력 객체를 가짐."""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    free_text: Mapped[str] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            native_enum=False,
            length=30,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # 검토를 만든 시점의 기업 정보 버전과 기본값. 이후 기업 정보가 바뀌어도 그대로 둠.
    company_profile_version: Mapped[int] = mapped_column(Integer)
    company_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    # 항목 이름 → {"value", "source", "confirmed"}. 형식은 intake.py 참고.
    intake: Mapped[dict[str, Any]] = mapped_column(JSON)
    intake_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
