import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.models import Company, WasteProfile
from app.domains.companies.schemas import CompanyCreate


class CompanyAlreadyExistsError(Exception):
    pass


async def get_company_by_owner(db: AsyncSession, owner_user_id: uuid.UUID) -> Company | None:
    return await db.scalar(select(Company).where(Company.owner_user_id == owner_user_id))


async def create_company(
    db: AsyncSession, owner_user_id: uuid.UUID, data: CompanyCreate
) -> Company:
    if await get_company_by_owner(db, owner_user_id):
        raise CompanyAlreadyExistsError

    company = Company(
        owner_user_id=owner_user_id,
        **data.model_dump(exclude={"waste_profiles"}),
        waste_profiles=[WasteProfile(**wp.model_dump()) for wp in data.waste_profiles],
    )
    db.add(company)
    try:
        await db.commit()
    except IntegrityError as exc:  # concurrent onboarding by the same user
        await db.rollback()
        raise CompanyAlreadyExistsError from exc
    await db.refresh(company, ["waste_profiles"])
    return company
