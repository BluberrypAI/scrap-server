"""Completion criteria from docs/specs/company-onboarding.md."""

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.models import CompanyProfileHistory

COMPANIES = "/api/v1/companies"
ME = "/api/v1/companies/me"
HISTORY = "/api/v1/companies/me/history"

COMPANY = {
    "company_name": "가상사출(주)",
    "business_registration_no": "123-45-67890",
    "representative_name": "홍대표",
    "industry": "플라스틱 사출 성형",
    "head_office_address": "경기도 시흥시 정왕동 시화산업단지",
    "contact": {"name": "김담당", "phone": "031-123-4567"},
    "main_waste_types": [
        {"category": "PP", "generation_cycle": "monthly", "expected_monthly_volume_kg": 3000},
        {"category": "PE", "generation_cycle": "irregular"},
    ],
}


@pytest.fixture
async def onboarded(auth_client: AsyncClient) -> AsyncClient:
    res = await auth_client.post(COMPANIES, json=COMPANY)
    assert res.status_code == 201
    return auth_client


async def history_count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(CompanyProfileHistory))


# --- 등록·조회 ---


async def test_create_company_returns_201_with_version_1(auth_client: AsyncClient):
    res = await auth_client.post(COMPANIES, json=COMPANY)

    assert res.status_code == 201
    body = res.json()
    assert body["company_name"] == COMPANY["company_name"]
    assert body["contact"] == {"name": "김담당", "phone": "031-123-4567", "email": None}
    assert [w["category"] for w in body["main_waste_types"]] == ["PP", "PE"]
    assert body["main_waste_types"][1]["expected_monthly_volume_kg"] is None
    assert body["profile_version"] == 1


async def test_second_company_for_same_user_returns_409(onboarded: AsyncClient):
    res = await onboarded.post(COMPANIES, json=COMPANY)
    assert res.status_code == 409


async def test_business_registration_no_is_stored_as_digits(onboarded: AsyncClient):
    res = await onboarded.get(ME)
    assert res.json()["business_registration_no"] == "1234567890"


@pytest.mark.parametrize("brn", ["123-45-6789", "12345678901", "abc-de-fghij"])
async def test_invalid_business_registration_no_returns_422(auth_client: AsyncClient, brn: str):
    res = await auth_client.post(COMPANIES, json={**COMPANY, "business_registration_no": brn})
    assert res.status_code == 422


async def test_invalid_generation_cycle_returns_422(auth_client: AsyncClient):
    payload = {**COMPANY, "main_waste_types": [{"category": "PP", "generation_cycle": "hourly"}]}

    res = await auth_client.post(COMPANIES, json=payload)

    assert res.status_code == 422


async def test_my_company_returns_404_before_onboarding(auth_client: AsyncClient):
    res = await auth_client.get(ME)
    assert res.status_code == 404


async def test_my_company_after_onboarding(onboarded: AsyncClient):
    res = await onboarded.get(ME)

    assert res.status_code == 200
    assert len(res.json()["main_waste_types"]) == 2
    assert res.json()["profile_version"] == 1


async def test_me_company_id_matches_after_onboarding(auth_client: AsyncClient):
    created = await auth_client.post(COMPANIES, json=COMPANY)

    res = await auth_client.get("/api/v1/users/me")

    assert res.json()["company_id"] == created.json()["id"]


async def test_create_company_requires_login(client: AsyncClient):
    res = await client.post(COMPANIES, json=COMPANY)
    assert res.status_code == 401


# --- 수정 ---


async def test_update_bumps_version_and_reports_changed_fields(onboarded: AsyncClient):
    new_contact = {"name": "이담당", "phone": None, "email": "lee@example.com"}

    res = await onboarded.patch(
        ME, json={"profile_version": 1, "industry": "플라스틱 압출 성형", "contact": new_contact}
    )

    assert res.status_code == 200
    assert res.json() == {"profile_version": 2, "changed_fields": ["industry", "contact"]}
    body = (await onboarded.get(ME)).json()
    assert body["industry"] == "플라스틱 압출 성형"
    assert body["contact"] == new_contact
    assert body["head_office_address"] == COMPANY["head_office_address"]
    assert body["profile_version"] == 2


async def test_update_replaces_waste_types(onboarded: AsyncClient):
    new_types = [{"category": "ABS", "generation_cycle": "weekly"}]

    res = await onboarded.patch(ME, json={"profile_version": 1, "main_waste_types": new_types})

    assert res.json()["changed_fields"] == ["main_waste_types"]
    types = (await onboarded.get(ME)).json()["main_waste_types"]
    assert [(t["category"], t["generation_cycle"]) for t in types] == [("ABS", "weekly")]


async def test_update_with_same_values_changes_nothing(onboarded: AsyncClient, db: AsyncSession):
    res = await onboarded.patch(
        ME,
        json={
            "profile_version": 1,
            "industry": COMPANY["industry"],
            "contact": COMPANY["contact"],
            "main_waste_types": COMPANY["main_waste_types"],
        },
    )

    assert res.json() == {"profile_version": 1, "changed_fields": []}
    assert await history_count(db) == 0


async def test_stale_version_returns_409_and_keeps_values(onboarded: AsyncClient):
    await onboarded.patch(ME, json={"profile_version": 1, "industry": "A"})

    res = await onboarded.patch(ME, json={"profile_version": 1, "industry": "B"})

    assert res.status_code == 409
    assert (await onboarded.get(ME)).json()["industry"] == "A"


async def test_concurrent_edit_from_same_version_returns_409(
    onboarded: AsyncClient, db: AsyncSession
):
    company_id = uuid.UUID((await onboarded.get(ME)).json()["id"])
    # Simulates another request that already committed version 2 from version 1.
    db.add(CompanyProfileHistory(company_id=company_id, profile_version=2, changed_fields=["x"]))
    await db.commit()

    res = await onboarded.patch(ME, json={"profile_version": 1, "industry": "B"})

    assert res.status_code == 409
    assert (await onboarded.get(ME)).json()["industry"] == COMPANY["industry"]


async def test_update_without_version_returns_422(onboarded: AsyncClient):
    res = await onboarded.patch(ME, json={"industry": "A"})
    assert res.status_code == 422


@pytest.mark.parametrize("field", ["company_name", "business_registration_no", "unknown"])
async def test_update_of_non_editable_field_returns_422(onboarded: AsyncClient, field: str):
    res = await onboarded.patch(ME, json={"profile_version": 1, field: "x"})
    assert res.status_code == 422


@pytest.mark.parametrize("field", ["industry", "head_office_address", "contact"])
async def test_update_to_null_returns_422(onboarded: AsyncClient, field: str):
    res = await onboarded.patch(ME, json={"profile_version": 1, field: None})
    assert res.status_code == 422


async def test_update_without_company_returns_404(auth_client: AsyncClient):
    res = await auth_client.patch(ME, json={"profile_version": 1, "industry": "A"})
    assert res.status_code == 404


# --- 변경 이력 ---


async def test_history_lists_newest_first(onboarded: AsyncClient):
    await onboarded.patch(ME, json={"profile_version": 1, "industry": "A"})
    await onboarded.patch(ME, json={"profile_version": 2, "head_office_address": "서울"})

    res = await onboarded.get(HISTORY)

    assert res.status_code == 200
    items = res.json()["items"]
    assert [(i["profile_version"], i["changed_fields"]) for i in items] == [
        (3, ["head_office_address"]),
        (2, ["industry"]),
    ]
    assert all(datetime.fromisoformat(i["changed_at"]).tzinfo for i in items)
    assert res.json()["pagingInfo"] == {
        "currentPageNumber": 1,
        "pageSize": 20,
        "elementCount": 2,
        "totalPageCount": 1,
        "isLastPage": True,
        "isEmpty": False,
    }


async def test_history_second_page(onboarded: AsyncClient):
    await onboarded.patch(ME, json={"profile_version": 1, "industry": "A"})
    await onboarded.patch(ME, json={"profile_version": 2, "industry": "B"})

    res = await onboarded.get(HISTORY, params={"pageNumber": 2, "pageSize": 1})

    body = res.json()
    assert [i["profile_version"] for i in body["items"]] == [2]
    assert body["pagingInfo"]["totalPageCount"] == 2
    assert body["pagingInfo"]["isLastPage"] is True


async def test_empty_history(onboarded: AsyncClient):
    res = await onboarded.get(HISTORY)

    body = res.json()
    assert body["items"] == []
    paging = body["pagingInfo"]
    assert (paging["elementCount"], paging["totalPageCount"], paging["isEmpty"]) == (0, 0, True)


@pytest.mark.parametrize("params", [{"pageSize": 101}, {"pageNumber": 0}])
async def test_history_invalid_paging_returns_422(onboarded: AsyncClient, params: dict):
    res = await onboarded.get(HISTORY, params=params)
    assert res.status_code == 422


async def test_history_without_company_returns_404(auth_client: AsyncClient):
    res = await auth_client.get(HISTORY)
    assert res.status_code == 404
