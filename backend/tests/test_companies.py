"""Completion criteria from docs/specs/company-onboarding.md."""

from httpx import AsyncClient

COMPANY = {
    "name": "가상사출(주)",
    "address": "경기도 시흥시 정왕동 시화산업단지",
    "industry": "플라스틱 사출 성형",
    "manager_name": "김담당",
    "waste_profiles": [
        {"category": "PP", "generation_cycle": "monthly", "expected_monthly_volume_kg": 3000},
        {"category": "PE", "generation_cycle": "irregular"},
    ],
}


async def test_create_company_returns_201_with_waste_profiles(auth_client: AsyncClient):
    res = await auth_client.post("/api/v1/companies", json=COMPANY)

    assert res.status_code == 201
    body = res.json()
    assert body["name"] == COMPANY["name"]
    assert [wp["category"] for wp in body["waste_profiles"]] == ["PP", "PE"]
    assert body["waste_profiles"][1]["expected_monthly_volume_kg"] is None


async def test_second_company_for_same_user_returns_409(auth_client: AsyncClient):
    await auth_client.post("/api/v1/companies", json=COMPANY)

    res = await auth_client.post("/api/v1/companies", json=COMPANY)

    assert res.status_code == 409


async def test_my_company_returns_404_before_onboarding(auth_client: AsyncClient):
    res = await auth_client.get("/api/v1/companies/me")
    assert res.status_code == 404


async def test_my_company_after_onboarding(auth_client: AsyncClient):
    await auth_client.post("/api/v1/companies", json=COMPANY)

    res = await auth_client.get("/api/v1/companies/me")

    assert res.status_code == 200
    assert len(res.json()["waste_profiles"]) == 2


async def test_me_company_id_matches_after_onboarding(auth_client: AsyncClient):
    created = await auth_client.post("/api/v1/companies", json=COMPANY)

    res = await auth_client.get("/api/v1/users/me")

    assert res.json()["company_id"] == created.json()["id"]


async def test_invalid_generation_cycle_returns_422(auth_client: AsyncClient):
    payload = {**COMPANY, "waste_profiles": [{"category": "PP", "generation_cycle": "hourly"}]}

    res = await auth_client.post("/api/v1/companies", json=payload)

    assert res.status_code == 422


async def test_create_company_requires_login(client: AsyncClient):
    res = await client.post("/api/v1/companies", json=COMPANY)
    assert res.status_code == 401
