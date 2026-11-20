"""Completion checks shared by combined output registration and legacy clients."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.domains.companies.models import Company
from app.domains.treatment.material_scope import FINISH_STATES
from app.domains.wastes.models import RouteStep, Waste, WasteCompletionSnapshot, WasteStatus


def completion_error(material, state, reference, intended_use, confirmed):
    if state not in FINISH_STATES.get(material, set()):
        return "현재 산출물은 완료 가능한 형태가 아닙니다. 추가 가공이나 보관 중을 선택해 주세요."
    if not confirmed or len((reference or "").strip()) < 3 or len((intended_use or "").strip()) < 3:
        return "완료하려면 산출물 근거·용도와 완료 확인이 필요합니다."
    return None


async def complete_lot(db, lot):
    lot.status = "completed"
    now = datetime.now(UTC)
    waste = await db.get(Waste, lot.id)
    waste.status = WasteStatus.COMPLETED
    waste.completed_at = now
    owner = await db.get(Company, lot.owner_company_id)
    db.add(
        WasteCompletionSnapshot(
            waste_id=lot.id,
            company_name=owner.company_name,
            site_name=owner.site_name,
            site_address=owner.site_address,
            completed_at=now,
        )
    )
    for step in await db.scalars(select(RouteStep).where(RouteStep.waste_id == lot.id)):
        step.status = "완료"
