import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

REPLY_LINK_PROVIDER = "reply-link"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "provider_subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 로그인 수단은 사용자당 하나. (provider, provider_subject)가 사용자를 식별함
    provider: Mapped[str] = mapped_column(String(20))
    provider_subject: Mapped[str] = mapped_column(String(255))
    # 표시·연락용. 식별에는 쓰지 않음
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    # Withdrawn users are blocked at once and purged after deletion_scheduled_at.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    @property
    def is_withdrawn(self) -> bool:
        return self.withdrawn_at is not None

    @property
    def is_guest(self) -> bool:
        return self.provider == REPLY_LINK_PROVIDER
