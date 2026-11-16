import pytest

from tests.test_companies import COMPANIES, COMPANY, ME
from tests.test_pp_company_workflow import setup_flow as setup_flow


@pytest.mark.parametrize(
    "point",
    [
        {"site_latitude": 37},
        {"site_latitude": 91, "site_longitude": 127},
        {"site_latitude": 37, "site_longitude": None},
        {"site_latitude": 37, "site_longitude": 181},
    ],
)
async def test_invalid_or_partial_point_is_rejected(auth_client, point):
    assert (await auth_client.post(COMPANIES, json={**COMPANY, **point})).status_code == 422


async def test_company_point_persists_and_address_change_clears_it(auth_client):
    point = {"site_latitude": 37.16, "site_longitude": 126.9}
    created = await auth_client.post(COMPANIES, json={**COMPANY, **point})
    assert created.status_code == 201
    assert created.json()["site_latitude"] == 37.16
    unchanged = await auth_client.patch(ME, json={"profile_version": 1, **point})
    assert unchanged.json()["changed_fields"] == []
    changed = await auth_client.patch(
        ME, json={"profile_version": 1, "site_address": "다른 사업장"}
    )
    assert set(changed.json()["changed_fields"]) == {"site_address", *point}
    assert (await auth_client.get(ME)).json()["site_latitude"] is None
    assert (await auth_client.patch(ME, json={"profile_version": 2, **point})).status_code == 200
    assert (
        await auth_client.patch(
            ME, json={"profile_version": 3, "site_latitude": None, "site_longitude": None}
        )
    ).status_code == 200
    assert (await auth_client.get(ME)).json()["site_longitude"] is None


async def test_location_change_invalidates_review_and_keeps_all_ai_candidates(setup_flow, db):
    from app.domains.companies.models import Company

    req, create, actors, packets = setup_flow
    lot = await create()
    first = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    cid = first["current_company_id"]
    import uuid

    company = await db.get(Company, uuid.UUID(cid))
    company.site_latitude, company.site_longitude = 37.16, 126.9
    company.profile_version += 1
    await db.commit()
    count = len(packets)
    second = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    assert second["review"]["origin"] == {"latitude": 37.16, "longitude": 126.9}
    assert len(packets) > count
    facilities = [f for o in second["review"]["next_step"]["options"] for f in o["facilities"]]
    assert set(second["review"]["results"]) == {f["capability_key"] for f in facilities}
    ranked = {f["facility_key"] for f in facilities if f["distance_rank"]}
    assert 0 < len(ranked) <= 5


async def test_profile_changed_during_ai_review_is_not_saved(setup_flow, db, monkeypatch):
    import uuid

    from app.domains.companies.models import Company
    from app.domains.transport import workflow

    req, create, _, _ = setup_flow
    lot = await create()
    original = workflow.review_intakes

    async def moving_company(packets, settings, *, lot_context):
        result = await original(packets, settings, lot_context=lot_context)
        company = await db.get(Company, uuid.UUID(lot["current_company_id"]))
        company.profile_version += 1
        await db.commit()
        return result

    monkeypatch.setattr(workflow, "review_intakes", moving_company)
    result = await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    assert result.status_code == 409
    assert (await req("A", f"/lots/{lot['id']}", method="GET")).json()["review"] is None
