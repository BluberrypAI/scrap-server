"""Versioned, self-declared site intake conditions; not permit certification."""

import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.domains.transport.models import SupplierIntakePolicy, WorkflowFacilityAccount
from app.domains.transport.schemas import PolicyWrite
from app.domains.treatment.repository import read_reference


def enabled(binding):
    return not binding.synthetic or get_settings().app_env in {"local", "test"}


def snapshot(row):
    return {
        "version": row.version,
        "company_id": str(row.company_id),
        "updated_at": row.created_at.replace(tzinfo=row.created_at.tzinfo or UTC).isoformat(),
        "basis": "supplier_declared_not_certified",
        "policy": row.data,
    }


async def current_policies(db):
    rows = await db.scalars(
        select(SupplierIntakePolicy)
        .join(
            WorkflowFacilityAccount,
            SupplierIntakePolicy.facility_key == WorkflowFacilityAccount.facility_key,
        )
        .where(SupplierIntakePolicy.company_id == WorkflowFacilityAccount.company_id)
        .order_by(SupplierIntakePolicy.version.desc())
    )
    bindings = {b.facility_key: b for b in await db.scalars(select(WorkflowFacilityAccount))}
    result = {}
    for row in rows:
        if row.facility_key not in result and enabled(bindings[row.facility_key]):
            result[row.facility_key] = snapshot(row)
    return result


async def my_policies(db, cid: uuid.UUID):
    ref, _ = await read_reference(db)
    labels = {f.key: f.label for f in ref.facilities}
    current = await current_policies(db)
    bindings = await db.scalars(
        select(WorkflowFacilityAccount).where(WorkflowFacilityAccount.company_id == cid)
    )
    return [
        {
            "facility_key": b.facility_key,
            "label": labels.get(b.facility_key, b.facility_key),
            "synthetic": b.synthetic,
            "current": current.get(b.facility_key),
        }
        for b in bindings
        if enabled(b)
    ]


async def save_policy(db, cid: uuid.UUID, body: PolicyWrite):
    binding = await db.scalar(
        select(WorkflowFacilityAccount)
        .where(WorkflowFacilityAccount.facility_key == body.facility_key)
        .with_for_update()
    )
    if not binding or binding.company_id != cid or not enabled(binding):
        raise AppError(403, ErrorCode.FORBIDDEN, "연결된 자기 사업장의 조건만 등록할 수 있습니다.")
    last = await db.scalar(
        select(SupplierIntakePolicy)
        .where(SupplierIntakePolicy.facility_key == body.facility_key)
        .order_by(SupplierIntakePolicy.version.desc())
        .limit(1)
    )
    version = last.version if last else 0
    if version != body.expected_version:
        raise AppError(409, ErrorCode.VERSION_CONFLICT, "조건이 변경됐습니다. 새로고침해 주세요.")
    row = SupplierIntakePolicy(
        facility_key=body.facility_key,
        company_id=cid,
        version=version + 1,
        data=body.policy.model_dump(),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError(
            409, ErrorCode.VERSION_CONFLICT, "조건이 변경됐습니다. 새로고침해 주세요."
        ) from None
    await db.refresh(row)
    return snapshot(row)
