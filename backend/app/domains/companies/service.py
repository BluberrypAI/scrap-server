import uuid
from collections.abc import Sequence

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.models import Company, CompanyProfileHistory, WasteProfile
from app.domains.companies.schemas import CompanyCreate, CompanyUpdate, WasteProfileCreate


class CompanyAlreadyExistsError(Exception):
    pass


class VersionConflictError(Exception):
    pass


async def get_company_by_owner(db: AsyncSession, owner_user_id: uuid.UUID) -> Company | None:
    return await db.scalar(select(Company).where(Company.owner_user_id == owner_user_id))


def _waste_profiles(items: Sequence[WasteProfileCreate]) -> list[WasteProfile]:
    return [WasteProfile(**item.model_dump()) for item in items]


async def create_company(
    db: AsyncSession, owner_user_id: uuid.UUID, data: CompanyCreate
) -> Company:
    if await get_company_by_owner(db, owner_user_id):
        raise CompanyAlreadyExistsError

    company = Company(
        owner_user_id=owner_user_id,
        **data.model_dump(exclude={"contact", "main_waste_types"}),
        contact_name=data.contact.name,
        contact_phone=data.contact.phone,
        contact_email=data.contact.email,
        waste_profiles=_waste_profiles(data.main_waste_types),
    )
    db.add(company)
    try:
        await db.commit()
    except IntegrityError as exc:  # concurrent onboarding by the same user
        await db.rollback()
        raise CompanyAlreadyExistsError from exc
    await db.refresh(company, ["waste_profiles"])
    return company


def _apply_changes(company: Company, data: CompanyUpdate) -> list[str]:
    """Copy sent fields onto the company and return the API names of those that differ."""
    sent = data.model_fields_set
    changed: list[str] = []

    for field in ("industry", "head_office_address"):
        value = getattr(data, field)
        if field in sent and value != getattr(company, field):
            setattr(company, field, value)
            changed.append(field)

    if "contact" in sent and data.contact is not None:
        new = (data.contact.name, data.contact.phone, data.contact.email)
        if new != (company.contact_name, company.contact_phone, company.contact_email):
            company.contact_name, company.contact_phone, company.contact_email = new
            changed.append("contact")

    if "main_waste_types" in sent and data.main_waste_types is not None:
        current = [
            (w.category, w.generation_cycle, w.expected_monthly_volume_kg)
            for w in company.waste_profiles
        ]
        new_items = [
            (w.category, w.generation_cycle, w.expected_monthly_volume_kg)
            for w in data.main_waste_types
        ]
        if new_items != current:
            company.waste_profiles = _waste_profiles(data.main_waste_types)
            changed.append("main_waste_types")

    return changed


async def update_company(db: AsyncSession, company: Company, data: CompanyUpdate) -> list[str]:
    """Apply an edit made from data.profile_version. Returns the changed field names."""
    if data.profile_version != company.profile_version:
        raise VersionConflictError

    changed = _apply_changes(company, data)
    if not changed:
        return []

    company.profile_version += 1
    db.add(
        CompanyProfileHistory(
            company_id=company.id,
            profile_version=company.profile_version,
            changed_fields=changed,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:  # another edit from the same version committed first
        await db.rollback()
        raise VersionConflictError from exc
    return changed


async def list_history(
    db: AsyncSession, company_id: uuid.UUID, page_number: int, page_size: int
) -> tuple[list[CompanyProfileHistory], int]:
    """Return one page of history, newest first, and the total number of entries."""
    total = await db.scalar(
        select(func.count())
        .select_from(CompanyProfileHistory)
        .where(CompanyProfileHistory.company_id == company_id)
    )
    rows = await db.scalars(
        select(CompanyProfileHistory)
        .where(CompanyProfileHistory.company_id == company_id)
        .order_by(CompanyProfileHistory.profile_version.desc())
        .offset((page_number - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total or 0


def company_ids_of_owners(owner_user_ids: Sequence[uuid.UUID]) -> Select[tuple[uuid.UUID]]:
    """사용자들이 가진 기업 id 서브쿼리. 다른 도메인이 기업에 딸린 데이터를 지울 때 씀."""
    return select(Company.id).where(Company.owner_user_id.in_(owner_user_ids))


async def delete_companies_of_owners(db: AsyncSession, owner_user_ids: Sequence[uuid.UUID]) -> None:
    """Delete companies, their waste profiles and history for purged users. The caller commits."""
    company_ids = company_ids_of_owners(owner_user_ids)
    for child in (WasteProfile, CompanyProfileHistory):
        await db.execute(
            delete(child)
            .where(child.company_id.in_(company_ids))
            .execution_options(synchronize_session=False)
        )
    await db.execute(
        delete(Company)
        .where(Company.owner_user_id.in_(owner_user_ids))
        .execution_options(synchronize_session=False)
    )
