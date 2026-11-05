import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
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
