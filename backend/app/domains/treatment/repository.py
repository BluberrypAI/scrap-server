"""Load and read the authoritative treatment snapshots from the SCRAP database."""

from sqlalchemy import and_, cast, delete, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.treatment.directory import load_snapshot
from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.models import TreatmentFacilityListing, TreatmentSnapshot
from app.domains.treatment.reference import PlanningReference, digest, read_bundle


async def read_reference(db: AsyncSession):
    snapshot = await db.get(TreatmentSnapshot, "processes")
    if snapshot is None:
        raise TreatmentError("not-imported", "서버에 공정 참조 데이터를 적재해 주세요.")
    if digest(snapshot.payload) != snapshot.checksum:
        raise TreatmentError("integrity", "공정 참조 데이터 체크섬을 확인해 주세요.")
    return PlanningReference.model_validate(snapshot.payload), snapshot.checksum


async def read_registry(db: AsyncSession, *, recycling_only: bool, waste_code: str | None):
    listings = TreatmentFacilityListing
    snapshots = TreatmentSnapshot
    eligible = (listings.is_recycling if recycling_only else listings.is_treatment).is_(True)
    record = listings.record
    if db.get_bind().dialect.name == "postgresql":
        record = cast(record, JSONB)
        if waste_code:
            eligible = and_(eligible, record["waste_codes"].contains([waste_code]))
        record = record.op("-")("raw_record")
    # Read the manifest and applicable rows in one statement, including an empty registry.
    rows = (
        await db.execute(
            select(snapshots.checksum, snapshots.payload, record)
            .select_from(snapshots)
            .outerjoin(listings, eligible)
            .where(snapshots.kind == "registry")
            .order_by(listings.source_row)
        )
    ).all()
    if not rows:
        return None
    checksum, manifest, _ = rows[0]
    return {
        "generation": checksum,
        "manifest": manifest,
        "records": [record for _, _, record in rows if record is not None],
    }


async def replace_snapshots(db: AsyncSession, registry_path=None, expected_sha256=None):
    value = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    reference = value.model_dump(mode="json")
    snapshot = (
        load_snapshot(registry_path, "national-json", expected_sha256)
        if registry_path is not None
        else None
    )
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('scrap_treatment_import'))"))
    await db.merge(
        TreatmentSnapshot(kind="processes", checksum=digest(reference), payload=reference)
    )
    if snapshot is not None:
        records, manifest = snapshot
        await db.execute(delete(TreatmentFacilityListing))
        for start in range(0, len(records), 250):
            batch = [
                {
                    "listing_id": row["listing_id"],
                    "source_row": row["source_row"],
                    "is_recycling": row["is_recycling_registration"],
                    "is_treatment": (
                        row["is_recycling_registration"] or "처분업" in row["business_type"]
                    ),
                    "record": row,
                }
                for row in records[start : start + 250]
            ]
            await db.execute(insert(TreatmentFacilityListing), batch)
        await db.merge(
            TreatmentSnapshot(
                kind="registry", checksum=manifest["records_sha256"], payload=manifest
            )
        )
    await db.commit()
    return {
        "processes": len(value.transitions),
        "curated_sites": len(value.facilities),
        "registry_rows_imported": len(snapshot[0]) if snapshot else None,
    }
