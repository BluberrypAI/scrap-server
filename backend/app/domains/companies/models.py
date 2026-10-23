import uuid
from enum import StrEnum

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String, UniqueConstraint
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
    company_name: Mapped[str] = mapped_column(String(200))
    # Digits only (10). Not verified against the tax office.
    business_registration_no: Mapped[str] = mapped_column(String(10))
    representative_name: Mapped[str] = mapped_column(String(100))
    industry: Mapped[str] = mapped_column(String(100))
    head_office_address: Mapped[str] = mapped_column(String(500))
    contact_name: Mapped[str] = mapped_column(String(100))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    # Bumped on every edit that changes a value; clients send it back to detect conflicts.
    profile_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

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


class CompanyProfileHistory(Base, TimestampMixin):
    """One row per edit that changed a value. created_at is the change time."""

    __tablename__ = "company_profile_history"
    # Also rejects the second of two concurrent edits made from the same version.
    __table_args__ = (UniqueConstraint("company_id", "profile_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    profile_version: Mapped[int] = mapped_column(Integer)
    # API field names, e.g. ["industry", "contact"].
    changed_fields: Mapped[list[str]] = mapped_column(JSON)
