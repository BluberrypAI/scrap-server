import uuid
from enum import StrEnum

from sqlalchemy import Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class GenerationCycle(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    IRREGULAR = "irregular"


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # unique: one company per manager account (product-plan 2장).
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500))
    industry: Mapped[str] = mapped_column(String(100))
    manager_name: Mapped[str] = mapped_column(String(100))
    manager_phone: Mapped[str | None] = mapped_column(String(50))

    waste_profiles: Mapped[list["WasteProfile"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WasteProfile.created_at",
    )


class WasteProfile(Base, TimestampMixin):
    __tablename__ = "waste_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100))
    generation_cycle: Mapped[GenerationCycle] = mapped_column(
        Enum(
            GenerationCycle,
            native_enum=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # Left empty when unknown; never estimated (product-plan 4장).
    expected_monthly_volume_kg: Mapped[float | None] = mapped_column(Float)

    company: Mapped[Company] = relationship(back_populates="waste_profiles", lazy="raise")
