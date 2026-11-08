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
    "contact_email": "manager@example.com",
    "industry": "플라스틱 사출 성형",
    "site_name": "시흥 1공장",
    "site_address": "경기도 시흥시 정왕동 시화산업단지",
    "site_facilities": ["혼합시설", "세척시설"],
    "main_products": ["자동차 내장 부품"],
    "main_waste_types": [
        {"category": "PP", "generation_cycle": "monthly", "expected_monthly_volume_kg": 3000},
        {"category": "PE", "generation_cycle": "irregular"},
    ],
}
REQUIRED = (
    "company_name",
    "contact_email",
    "industry",
    "site_name",
    "site_address",
    "site_facilities",
    "main_products",
)


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
    for field in REQUIRED:
        assert body[field] == COMPANY[field]
    assert [w["category"] for w in body["main_waste_types"]] == ["PP", "PE"]
    assert all(uuid.UUID(w["id"]) for w in body["main_waste_types"])
    assert body["main_waste_types"][1]["expected_monthly_volume_kg"] is None
    assert body["profile_version"] == 1


async def test_main_waste_types_are_optional(auth_client: AsyncClient):
    payload = {k: v for k, v in COMPANY.items() if k != "main_waste_types"}

    res = await auth_client.post(COMPANIES, json=payload)

    assert res.status_code == 201
    assert res.json()["main_waste_types"] == []


@pytest.mark.parametrize("field", REQUIRED)
async def test_missing_required_field_returns_422(auth_client: AsyncClient, field: str):
    payload = {k: v for k, v in COMPANY.items() if k != field}

    res = await auth_client.post(COMPANIES, json=payload)

    assert res.status_code == 422


@pytest.mark.parametrize("field", ["site_facilities", "main_products"])
async def test_empty_name_list_returns_422(auth_client: AsyncClient, field: str):
    res = await auth_client.post(COMPANIES, json={**COMPANY, field: []})
    assert res.status_code == 422


async def test_invalid_contact_email_returns_422(auth_client: AsyncClient):
    res = await auth_client.post(COMPANIES, json={**COMPANY, "contact_email": "not-an-email"})
    assert res.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["business_registration_no", "representative_name", "head_office_address", "contact"],
)
async def test_removed_field_returns_422(auth_client: AsyncClient, field: str):
    res = await auth_client.post(COMPANIES, json={**COMPANY, field: "x"})
    assert res.status_code == 422


async def test_second_company_for_same_user_returns_409(onboarded: AsyncClient):
    res = await onboarded.post(COMPANIES, json=COMPANY)
    assert res.status_code == 409


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
    assert res.json()["site_facilities"] == COMPANY["site_facilities"]
    assert len(res.json()["main_waste_types"]) == 2
    assert res.json()["profile_version"] == 1


async def test_me_company_id_is_null_before_onboarding(auth_client: AsyncClient):
    res = await auth_client.get("/api/v1/users/me")
    assert res.json()["company_id"] is None


async def test_me_company_id_matches_after_onboarding(auth_client: AsyncClient):
    created = await auth_client.post(COMPANIES, json=COMPANY)

    res = await auth_client.get("/api/v1/users/me")

    assert res.json()["company_id"] == created.json()["id"]


async def test_create_company_requires_login(client: AsyncClient):
    res = await client.post(COMPANIES, json=COMPANY)
    assert res.status_code == 401


# --- 수정 ---


async def test_update_bumps_version_and_reports_changed_fields(onboarded: AsyncClient):
    res = await onboarded.patch(
        ME,
        json={
            "profile_version": 1,
            "industry": "플라스틱 압출 성형",
            "main_products": ["포장 필름"],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"profile_version": 2, "changed_fields": ["industry", "main_products"]}
    body = (await onboarded.get(ME)).json()
    assert body["industry"] == "플라스틱 압출 성형"
    assert body["main_products"] == ["포장 필름"]
    assert body["site_address"] == COMPANY["site_address"]
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
            "site_facilities": COMPANY["site_facilities"],
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


@pytest.mark.parametrize("field", ["business_registration_no", "head_office_address", "unknown"])
async def test_update_of_unknown_field_returns_422(onboarded: AsyncClient, field: str):
    res = await onboarded.patch(ME, json={"profile_version": 1, field: "x"})
    assert res.status_code == 422


@pytest.mark.parametrize("field", ["company_name", "industry", "site_facilities"])
async def test_update_to_null_returns_422(onboarded: AsyncClient, field: str):
    res = await onboarded.patch(ME, json={"profile_version": 1, field: None})
    assert res.status_code == 422


async def test_update_without_company_returns_404(auth_client: AsyncClient):
    res = await auth_client.patch(ME, json={"profile_version": 1, "industry": "A"})
    assert res.status_code == 404


# --- 변경 이력 ---


async def test_history_lists_newest_first(onboarded: AsyncClient):
    await onboarded.patch(ME, json={"profile_version": 1, "industry": "A"})
    await onboarded.patch(ME, json={"profile_version": 2, "site_address": "서울"})

    res = await onboarded.get(HISTORY)

    assert res.status_code == 200
    items = res.json()["items"]
    assert [(i["profile_version"], i["changed_fields"]) for i in items] == [
        (3, ["site_address"]),
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
