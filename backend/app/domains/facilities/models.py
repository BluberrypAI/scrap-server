import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Facility(Base, TimestampMixin):
    """검색할 수 있게 정리한 처리·재활용 시설. facility_import_rows 원본에서 옮겨 적재함."""

    __tablename__ = "facilities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # 업종 (중간처분업, 종합재활용업 등)
    business_type: Mapped[str | None] = mapped_column(String(100))
    permit_no: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(500))
    # 거리 계산용 좌표. 지오코딩 전에는 비어 있음
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # 화면에 보여줄 취급 품목 이름 목록 (예: 폐유, 폐유기용제)
    materials: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    # 반입 조건 목록
    acceptance_conditions: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    source: Mapped[str | None] = mapped_column(String(100))
    source_date: Mapped[date | None] = mapped_column(Date)
    # 시설 정보를 바꿀 때마다 1씩 오름
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # 원본 행. unique: 원본 1행 = 시설 1곳
    import_row_id: Mapped[str | None] = mapped_column(
        ForeignKey("facility_import_rows.listing_id", ondelete="SET NULL"), unique=True
    )


class FacilityWasteCode(Base):
    """시설이 허가받은 폐기물 분류번호. 검증된 허가 조합만 적재함."""

    __tablename__ = "facility_waste_codes"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), primary_key=True
    )
    waste_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 취급 방식 (재활용, 처분)
    handling: Mapped[str | None] = mapped_column(String(50))


class FacilityRType(Base):
    """시설이 허가 분류번호별로 수행하는 재활용 유형(R코드).

    (facility_id, waste_code) 복합 FK로 facility_waste_codes를 참조해서,
    허가받지 않은 분류번호에는 R유형을 붙일 수 없음.
    """

    __tablename__ = "facility_r_types"
    __table_args__ = (
        ForeignKeyConstraint(
            ["facility_id", "waste_code"],
            ["facility_waste_codes.facility_id", "facility_waste_codes.waste_code"],
            ondelete="CASCADE",
            name="fk_facility_r_types_facility_waste_codes",
        ),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    waste_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 재활용 유형 코드 (예: R-4-1)
    r_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    r_name: Mapped[str | None] = mapped_column(String(200))
    # 재활용 유형 분류 (물질 재활용, 에너지 회수 등)
    category: Mapped[str | None] = mapped_column(String(50))
