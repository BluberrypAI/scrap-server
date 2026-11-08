from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

RECORD = JSON().with_variant(JSONB(), "postgresql")


class TreatmentSnapshot(Base):
    __tablename__ = "treatment_snapshots"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    checksum: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(RECORD)


class FacilityImportRow(Base):
    __tablename__ = "facility_import_rows"

    listing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, unique=True)
    is_recycling: Mapped[bool] = mapped_column(Boolean)
    is_treatment: Mapped[bool] = mapped_column(Boolean, index=True)
    record: Mapped[dict] = mapped_column(RECORD)
