import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.transport.models import TransportHandoff
from app.domains.transport.schemas import TransportCreate, TransportEvent
from app.domains.transport.shared import prepare_registration, recipient_for


async def register(db: AsyncSession, key: uuid.UUID, owner: uuid.UUID, data: TransportCreate):
    record = await db.get(TransportHandoff, key)
    fields = data.model_dump(include={"lot", "origin", "destination"})
    if record is None:
        try:
            binding = None
            if data.shared_case_id or (
                data.case_update and await recipient_for(db, data.destination_key)
            ):
                binding = await prepare_registration(db, key, owner, data)
                if not binding:
                    return None
            record = TransportHandoff(
                id=key,
                owner_id=owner,
                expires_at=datetime.now(UTC) + timedelta(days=7),
                **fields,
                shared_case_id=binding[0] if binding else None,
                recipient_id=binding[1] if binding else None,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
        except IntegrityError:
            await db.rollback()
            record = await db.get(TransportHandoff, key)
    if record is None or record.owner_id != owner:
        return None
    if any(getattr(record, name) != value for name, value in fields.items()):
        return None
    return await read(db, key)


async def read(db: AsyncSession, key: uuid.UUID):
    record = await db.get(TransportHandoff, key)
    if record and record.expires_at.replace(tzinfo=record.expires_at.tzinfo or UTC) > datetime.now(
        UTC
    ):
        return record
    return None


async def record_event(db: AsyncSession, key: uuid.UUID, event: TransportEvent):
    now = datetime.now(UTC)
    stmt = update(TransportHandoff).where(
        TransportHandoff.id == key,
        TransportHandoff.expires_at > now,
        TransportHandoff.receipt_at.is_(None),
    )
    if event.role == "driver":
        stmt = stmt.where(TransportHandoff.pickup_at.is_(None)).values(
            pickup_actor=event.actor, pickup_at=now
        )
    else:
        stmt = stmt.values(receipt_actor=event.actor, receipt_at=now)
    await db.execute(stmt.execution_options(synchronize_session=False))
    await db.commit()
    await db.get(TransportHandoff, key, populate_existing=True)
    return await read(db, key)
