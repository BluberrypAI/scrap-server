"""ERD v2 제약 조건 (docs/specs/erd-v2-alignment.md 완료 조건)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.models import Company
from app.domains.facilities.models import Facility, FacilityRType, FacilityWasteCode
from app.domains.users.models import User
from app.domains.wastes.models import (
    CheckRole,
    ImmutableRowError,
    QrFieldCheck,
    RouteStep,
    Waste,
    WasteCompletionSnapshot,
    WasteStatus,
)
from tests.conftest import COMPANY_PAYLOAD


@pytest.fixture
async def fk_db(db: AsyncSession) -> AsyncSession:
    # SQLite는 FK 검사가 기본으로 꺼져 있음. PostgreSQL은 항상 검사함
    if db.bind.dialect.name == "sqlite":
        await db.execute(text("PRAGMA foreign_keys=ON"))
    return db


@pytest.fixture
async def company(fk_db: AsyncSession, user: User) -> Company:
    fields = {k: v for k, v in COMPANY_PAYLOAD.items() if k != "main_waste_types"}
    company = Company(user_id=user.id, main_waste_types=[], **fields)
    fk_db.add(company)
    await fk_db.commit()
    return company


async def _waste(db: AsyncSession, company: Company, name: str = "폐합성수지") -> Waste:
    waste = Waste(company_id=company.id, name=name)
    db.add(waste)
    await db.flush()
    return waste


async def _step(db: AsyncSession, waste: Waste, seq: int = 1) -> RouteStep:
    step = RouteStep(waste_id=waste.id, seq=seq, stage="수집·운반")
    db.add(step)
    await db.flush()
    return step


async def test_waste_defaults(fk_db: AsyncSession, company: Company):
    await _waste(fk_db, company, "기본값 확인")
    await fk_db.commit()
    # DB에는 enum 이름이 아니라 값(diagnosing)이 저장됨
    stored = await fk_db.scalar(text("SELECT status FROM wastes WHERE name = '기본값 확인'"))
    assert stored == WasteStatus.DIAGNOSING.value


async def test_route_step_seq_unique_per_waste(fk_db: AsyncSession, company: Company):
    waste = await _waste(fk_db, company)
    await _step(fk_db, waste, seq=1)
    fk_db.add(RouteStep(waste_id=waste.id, seq=1, stage="중간처리"))
    with pytest.raises(IntegrityError):
        await fk_db.flush()


async def test_qr_check_without_step(fk_db: AsyncSession, company: Company):
    waste = await _waste(fk_db, company)
    # route_step_id가 비어 있으면 같은 역할을 여러 번 남길 수 있음
    for _ in range(2):
        fk_db.add(QrFieldCheck(waste_id=waste.id, role=CheckRole.DRIVER, actor_name="김운반"))
    await fk_db.commit()


async def test_qr_check_step_must_belong_to_same_waste(fk_db: AsyncSession, company: Company):
    waste_a = await _waste(fk_db, company, "A")
    waste_b = await _waste(fk_db, company, "B")
    step_b = await _step(fk_db, waste_b)
    fk_db.add(
        QrFieldCheck(
            waste_id=waste_a.id,
            route_step_id=step_b.id,
            role=CheckRole.DRIVER,
            actor_name="김운반",
        )
    )
    with pytest.raises(IntegrityError):
        await fk_db.flush()


async def test_qr_check_once_per_step_and_role(fk_db: AsyncSession, company: Company):
    waste = await _waste(fk_db, company)
    step = await _step(fk_db, waste)
    fk_db.add(
        QrFieldCheck(
            waste_id=waste.id, route_step_id=step.id, role=CheckRole.DRIVER, actor_name="김운반"
        )
    )
    fk_db.add(
        QrFieldCheck(
            waste_id=waste.id,
            route_step_id=step.id,
            role=CheckRole.RECIPIENT,
            actor_name="이입고",
        )
    )
    await fk_db.flush()
    fk_db.add(
        QrFieldCheck(
            waste_id=waste.id, route_step_id=step.id, role=CheckRole.DRIVER, actor_name="박운반"
        )
    )
    with pytest.raises(IntegrityError):
        await fk_db.flush()


async def test_completion_snapshot_one_per_waste(fk_db: AsyncSession, company: Company):
    waste = await _waste(fk_db, company)
    now = datetime.now(UTC)
    for _ in range(2):
        fk_db.add(
            WasteCompletionSnapshot(
                waste_id=waste.id,
                company_name=company.company_name,
                site_name=company.site_name,
                site_address=company.site_address,
                completed_at=now,
            )
        )
    with pytest.raises(IntegrityError):
        await fk_db.flush()


async def test_completion_snapshot_is_immutable(fk_db: AsyncSession, company: Company):
    waste = await _waste(fk_db, company)
    snapshot = WasteCompletionSnapshot(
        waste_id=waste.id,
        company_name=company.company_name,
        site_name=company.site_name,
        site_address=company.site_address,
        completed_at=datetime.now(UTC),
    )
    fk_db.add(snapshot)
    await fk_db.commit()
    snapshot.company_name = "바뀐 이름"
    with pytest.raises(ImmutableRowError):
        await fk_db.flush()


async def test_facility_r_type_requires_permitted_code(fk_db: AsyncSession):
    facility = Facility(name="가상재활용(주)")
    fk_db.add(facility)
    await fk_db.flush()
    fk_db.add(FacilityWasteCode(facility_id=facility.id, waste_code="51-03-01"))
    await fk_db.flush()
    fk_db.add(FacilityRType(facility_id=facility.id, waste_code="51-03-01", r_code="R-4-1"))
    await fk_db.flush()
    # 허가받지 않은 분류번호에는 R유형을 붙일 수 없음
    fk_db.add(FacilityRType(facility_id=facility.id, waste_code="51-04-01", r_code="R-4-1"))
    with pytest.raises(IntegrityError):
        await fk_db.flush()


async def test_company_coordinates_default_null(company_client: AsyncClient):
    body = (await company_client.get("/api/v1/companies/me")).json()
    assert body["site_latitude"] is None
    assert body["site_longitude"] is None


async def test_main_products_null_rejected(auth_client: AsyncClient):
    payload = {**COMPANY_PAYLOAD, "main_products": None}
    res = await auth_client.post("/api/v1/companies", json=payload)
    assert res.status_code == 422


async def test_main_products_db_default(fk_db: AsyncSession, user: User):
    # 컬럼을 빼고 넣어도 DB 기본값 '[]'로 채워짐
    company_id = uuid.uuid4()
    fields = {k: v for k, v in COMPANY_PAYLOAD.items() if k not in ("main_products",)}
    fk_db.add(Company(id=company_id, user_id=user.id, **fields))
    await fk_db.commit()
    company = await fk_db.scalar(select(Company).where(Company.id == company_id))
    assert company.main_products == []


async def test_purge_deletes_wastes(fk_db: AsyncSession, company: Company, user: User):
    from datetime import timedelta

    from app.domains.users.service import purge_withdrawn_users

    waste = await _waste(fk_db, company)
    step = await _step(fk_db, waste)
    fk_db.add(
        QrFieldCheck(
            waste_id=waste.id, route_step_id=step.id, role=CheckRole.DRIVER, actor_name="김운반"
        )
    )
    user.withdrawn_at = datetime.now(UTC) - timedelta(days=40)
    user.deletion_scheduled_at = datetime.now(UTC) - timedelta(days=10)
    await fk_db.commit()
    assert await purge_withdrawn_users(fk_db) == 1
    assert await fk_db.scalar(select(Waste.id)) is None
    assert await fk_db.scalar(select(RouteStep.id)) is None
    assert await fk_db.scalar(select(QrFieldCheck.id)) is None
