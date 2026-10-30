import uuid
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


def _enum(cls: type[StrEnum]) -> Enum:
    return Enum(cls, native_enum=False, length=30, values_callable=lambda e: [m.value for m in e])


class Decision(StrEnum):
    CONFIRM = "confirm"
    # 자료를 요청하고 같은 단계에 머묾
    REQUEST_EVIDENCE = "request_evidence"
    HOLD = "hold"


class ProceedOption(StrEnum):
    # 심각 리스크를 보류한 채 다음 단계로 감
    HOLD_AND_PROCEED = "hold_and_proceed"
    # 이 후보를 사용자 판단으로 제외함
    EXCLUDE = "exclude"


class RiskStepDecision(Base, TimestampMixin):
    """후보의 공정 단계별 결정 기록. 같은 단계에 여러 번 남을 수 있고 마지막 기록이 유효함."""

    __tablename__ = "risk_step_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(200))
    step_no: Mapped[int] = mapped_column(Integer)
    decision: Mapped[Decision] = mapped_column(_enum(Decision))
    proceed_option: Mapped[ProceedOption | None] = mapped_column(_enum(ProceedOption))


class RiskEvidence(Base, TimestampMixin):
    """리스크에 연결한 증빙. 연결된 리스크만 해소(resolved)로 봄."""

    __tablename__ = "risk_evidence"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(200))
    risk_id: Mapped[str] = mapped_column(String(300))
    supplement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplements.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
