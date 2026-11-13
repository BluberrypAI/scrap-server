import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TransportHandoff(Base, TimestampMixin):
    __tablename__ = "transport_handoffs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lot: Mapped[str] = mapped_column(String(160))
    origin: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(160))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pickup_actor: Mapped[str | None] = mapped_column(String(80))
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_actor: Mapped[str | None] = mapped_column(String(80))
    receipt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shared_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transport_shared_cases.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def account_required(self):
        return self.shared_case_id is not None


class TransportSharedCase(Base, TimestampMixin):
    __tablename__ = "transport_shared_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    active_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON)


class WorkflowLot(Base, TimestampMixin):
    __tablename__ = "workflow_lots"
    __table_args__ = (UniqueConstraint("owner_company_id", "diagnosis_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wastes.id", ondelete="CASCADE"), primary_key=True
    )
    owner_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    current_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    diagnosis_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    data: Mapped[dict] = mapped_column(JSON)
    review: Mapped[dict | None] = mapped_column(JSON)


class WorkflowFacilityAccount(Base, TimestampMixin):
    __tablename__ = "workflow_facility_accounts"
    facility_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    verification_reference: Mapped[str] = mapped_column(String(300))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkflowOffer(Base, TimestampMixin):
    __tablename__ = "workflow_offers"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_lots.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    data: Mapped[dict] = mapped_column(JSON)
    qr_hash: Mapped[str | None] = mapped_column(String(64))
    qr_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    route_step_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_steps.id"))


class WorkflowPhoto(Base, TimestampMixin):
    __tablename__ = "workflow_photos"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_lots.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    stage: Mapped[int] = mapped_column(Integer)
    mime: Mapped[str] = mapped_column(String(30))
    content: Mapped[bytes] = mapped_column(LargeBinary)
