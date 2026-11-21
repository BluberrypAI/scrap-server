import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.models import Company, CompanyProfileHistory
from app.domains.companies.schemas import (
    EDITABLE_FIELDS,
    SITE_CONDITION_FIELDS,
    CompanyCreate,
    CompanyUpdate,
    WasteTypeCreate,
)
from app.domains.wastes import repository as waste_repo


class CompanyAlreadyExistsError(Exception):
    pass


class VersionConflictError(Exception):
    pass


async def get_company_by_user(db: AsyncSession, user_id: uuid.UUID) -> Company | None:
    return await db.scalar(select(Company).where(Company.user_id == user_id))


def site_condition_facts(company: Company) -> dict[str, Any]:
    """문진 엔진 confirmed_facts로 넘길 사업장 고정값. 값이 있는 것만 담음."""
    return {
        f: getattr(company, f) for f in SITE_CONDITION_FIELDS if getattr(company, f) is not None
    }


def _waste_types(items: Sequence[WasteTypeCreate]) -> list[dict[str, Any]]:
    """API 항목을 JSON 저장 형식으로 바꿈. 항목마다 id를 새로 붙임."""
    return [{"id": str(uuid.uuid4()), **item.model_dump(mode="json")} for item in items]


async def create_company(db: AsyncSession, user_id: uuid.UUID, data: CompanyCreate) -> Company:
    if await get_company_by_user(db, user_id):
        raise CompanyAlreadyExistsError

    company = Company(
        user_id=user_id,
        **data.model_dump(exclude={"main_waste_types"}),
        main_waste_types=_waste_types(data.main_waste_types),
    )
    db.add(company)
    try:
        await db.commit()
    except IntegrityError as exc:  # concurrent onboarding by the same user
        await db.rollback()
        raise CompanyAlreadyExistsError from exc
    return company


def _without_ids(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in item.items() if k != "id"} for item in items]


def _apply_changes(company: Company, data: CompanyUpdate) -> list[str]:
    """Copy sent fields onto the company and return the API names of those that differ."""
    sent = data.model_fields_set
    changed: list[str] = []

    for field in EDITABLE_FIELDS:
        value = getattr(data, field)
        if field not in sent:
            continue
        if field == "main_waste_types":
            new = _waste_types(value)
            if _without_ids(new) == _without_ids(company.main_waste_types):
                continue
            value = new
        elif value == getattr(company, field):
            continue
        # JSON 컬럼은 새 객체를 넣어야 변경이 감지됨
        setattr(company, field, value)
        changed.append(field)

    # An old point must not follow a newly entered address.
    if "site_address" in changed and "site_latitude" not in sent:
        for field in ("site_latitude", "site_longitude"):
            if getattr(company, field) is not None:
                setattr(company, field, None)
                changed.append(field)
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


async def delete_companies_of_users(db: AsyncSession, user_ids: Sequence[uuid.UUID]) -> None:
    """Delete companies, their history and wastes for purged users. The caller commits."""
    company_ids = select(Company.id).where(Company.user_id.in_(user_ids))
    await waste_repo.delete_wastes_of_companies(db, company_ids)
    await db.execute(
        delete(CompanyProfileHistory)
        .where(CompanyProfileHistory.company_id.in_(company_ids))
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Company)
        .where(Company.user_id.in_(user_ids))
        .execution_options(synchronize_session=False)
    )
