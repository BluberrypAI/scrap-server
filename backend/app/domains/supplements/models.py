import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import Date, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.domains.documents.models import VerificationStatus


def _enum(cls: type[StrEnum], length: int = 30) -> Enum:
    return Enum(
        cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e]
    )


class SupplementType(StrEnum):
    INSPECTION_RESULT = "inspection_result"
    FACILITY_RESPONSE = "facility_response"
    QUOTE = "quote"
    SPECIFICATION = "specification"


class Applicability(StrEnum):
    # 적용 물량이 검토 물량과 같음
    MATCHED = "matched"
    # 물량이 다르거나 검토 물량이 확인되지 않아 이 검토에 그대로 쓸 수 없음
    MISMATCH = "mismatch"


class Supplement(Base, TimestampMixin):
    """실행 뒤 추가로 받은 자료 (검사 결과, 시설 회신, 견적, 규격)."""

    __tablename__ = "supplements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[SupplementType] = mapped_column(_enum(SupplementType))
    # 자료에 적힌 대표 값 (예: 견적 단가). 없으면 null
    value: Mapped[float | None] = mapped_column(Float)
    # 자료가 적용되는 물량 (kg로 환산해 저장)
    applied_quantity_kg: Mapped[float] = mapped_column(Float)
    effective_date: Mapped[date] = mapped_column(Date)
    verification_status: Mapped[VerificationStatus] = mapped_column(_enum(VerificationStatus, 20))
    applicability: Mapped[Applicability] = mapped_column(_enum(Applicability, 20))
    mismatch_reason: Mapped[str | None] = mapped_column(String(300))
    file_name: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(300))
