import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Company(Base, TimestampMixin):
    """회원이 온보딩에서 등록한 기업과 사업장(기업당 1곳). 행이 없으면 온보딩 전임."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # unique: 회원 1명 = 기업 1곳 (product-plan 2장)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    company_name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str] = mapped_column(String(320))
    industry: Mapped[str] = mapped_column(String(100))
    # 주생산품 이름 목록. 선택 항목이라 빈 목록일 수 있음
    main_products: Mapped[list[str]] = mapped_column(JSON)
    # [{"id", "category", "expected_monthly_volume_kg"}]. 선택 항목
    main_waste_types: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    site_name: Mapped[str] = mapped_column(String(200))
    site_address: Mapped[str] = mapped_column(String(500))
    # 운영 중인 배출시설 이름 목록 (예: 폐수처리시설)
    site_facilities: Mapped[list[str]] = mapped_column(JSON)
    # 값이 바뀌는 수정마다 1씩 오름. 클라이언트가 다시 보내 동시 수정을 감지함
    profile_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


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
    # API field names, e.g. ["industry", "site_name"].
    changed_fields: Mapped[list[str]] = mapped_column(JSON)
