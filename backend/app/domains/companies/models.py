import uuid
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, UniqueConstraint
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
    # 주생산품 이름 목록. 선택 항목이라 빈 목록일 수 있음 (NULL은 저장하지 않음)
    main_products: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    # [{"id", "category", "expected_monthly_volume_kg"}]. 선택 항목
    main_waste_types: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    site_name: Mapped[str] = mapped_column(String(200))
    site_address: Mapped[str] = mapped_column(String(500))
    # 반경 검색 기준점. 지오코딩 전에는 비어 있음
    site_latitude: Mapped[float | None] = mapped_column(Float)
    site_longitude: Mapped[float | None] = mapped_column(Float)
    # 운영 중인 배출시설 이름 목록 (예: 폐수처리시설)
    site_facilities: Mapped[list[str]] = mapped_column(JSON)
    # 사업장폐기물 판정에 쓰는 회사 고정값 (문진 엔진 사실 이름과 같음). null = 모름·미입력
    # 값이 있으면 문진 건을 만들 때 엔진에 confirmed_facts로 넘겨 다시 묻지 않음
    emission_facility: Mapped[str | None] = mapped_column(String(3))  # yes | no
    daily_avg_kg: Mapped[float | None] = mapped_column(Float)
    public_facility: Mapped[str | None] = mapped_column(String(3))
    site_emits_designated: Mapped[str | None] = mapped_column(String(3))
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
