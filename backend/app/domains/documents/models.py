import uuid
from enum import StrEnum

from sqlalchemy import Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


def _enum(cls: type[StrEnum], length: int = 30) -> Enum:
    return Enum(
        cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e]
    )


class DocumentType(StrEnum):
    # 시험성적서. 검수된 측정값이 있으면 근거 등급 A (FR-1.6)
    TEST_REPORT = "test_report"
    OTHER = "other"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(255))
    # 확장자 기준 형식 (pdf, png, jpg, xlsx, csv)
    format: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType))
    status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus))
    # 파일 저장소 키. 교체할 때마다 바뀜
    storage_key: Mapped[str] = mapped_column(String(300))
    # 교체 횟수 + 1
    file_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class DocumentValue(Base, TimestampMixin):
    """문서에서 추출한 측정값 후보 1개. 사람이 검수해야 근거로 씀."""

    __tablename__ = "document_values"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # 측정 항목 이름 (예: 함수율, 납)
    name: Mapped[str] = mapped_column(String(200))
    # 읽지 못했거나 비어 있으면 null. 추정해 채우지 않음
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(40))
    # 원문 위치 (예: "p.2 표1 3행")와 측정 기준 (예: "건조 기준")
    source_location: Mapped[str | None] = mapped_column(String(300))
    basis: Mapped[str | None] = mapped_column(String(200))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus, 20),
        default=VerificationStatus.UNVERIFIED,
    )
