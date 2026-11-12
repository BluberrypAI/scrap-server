from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wastes.models import QrFieldCheck, RouteStep, Waste, WasteCompletionSnapshot


async def delete_wastes_of_companies(db: AsyncSession, company_ids: Select) -> None:
    """기업의 폐기물 건과 딸린 기록을 지움. 호출한 쪽이 commit함.

    SQLite는 FK cascade를 하지 않으므로 자식 테이블부터 직접 지움.
    """
    waste_ids = select(Waste.id).where(Waste.company_id.in_(company_ids))
    for model in (QrFieldCheck, WasteCompletionSnapshot, RouteStep):
        await db.execute(
            delete(model)
            .where(model.waste_id.in_(waste_ids))
            .execution_options(synchronize_session=False)
        )
    await db.execute(
        delete(Waste)
        .where(Waste.company_id.in_(company_ids))
        .execution_options(synchronize_session=False)
    )
