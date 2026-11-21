"""Exercise cookie login and handoff with a synthetic guest linked to one candidate."""

from copy import deepcopy
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domains.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.domains.transport.models import (
    WorkflowFacilityAccount,
    WorkflowInquiryReplyLink,
    WorkflowLot,
)
from app.main import app
from tests.test_pp_company_workflow import BASE
from tests.test_pp_company_workflow import setup_flow as _setup_flow
from tests.test_public_inquiry_replies import PUBLIC_PATH, assert_protected, issue
from tests.test_public_inquiry_replies import inquiry as _inquiry
from tests.test_public_inquiry_replies import public_client as _public_client
from tests.test_vendor_inquiry import reviewed

setup_flow = _setup_flow
inquiry = _inquiry
public_client = _public_client
COMPANY = "/api/v1/companies/me"
USER = "/api/v1/users/me"
REFRESH = "/api/v1/auth/refresh"


def candidate(lot, key):
    return next(
        (option, facility)
        for option in lot["review"]["next_step"]["options"]
        for facility in option["facilities"]
        if facility["capability_key"] == key
    )


async def issue_url(req, base):
    issued = await issue(req, base)
    return f"{PUBLIC_PATH}/{issued['token']}"


async def join(client, url, *, lot_visible=False):
    response = await client.post(url + "/join")
    assert response.status_code == 200, response.text
    assert response.json()["lot_visible"] is lot_visible
    assert_protected(response)
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2 and all("HttpOnly" in cookie for cookie in cookies)
    company = await client.get(COMPANY)
    assert company.status_code == 200, company.text
    assert company.json()["company_name"] == response.json()["company_name"]
    assert company.json()["guest"] is True
    return company.json()


async def test_join_reuses_account_and_hides_unoffered_lot(inquiry, db, public_client):
    req, lot, body, base, _ = inquiry
    option, facility = candidate(lot, body["capability_key"])
    url = await issue_url(req, base)
    assert (await public_client.get(url)).json()["joined"] is False
    company = await join(public_client, url)
    assert company["company_name"] == f"{facility['label']} (링크 참여)"
    assert company["site_name"] == facility["label"]
    assert company["site_address"] == (facility["address"] or "")
    assert company["site_facilities"] == [option["label"]]
    assert company["contact_email"] == ""
    assert company["industry"] == "폐기물 재활용업"
    user = (await public_client.get(USER)).json()
    assert user["guest"] is True and user["provider"] == "reply-link"
    assert user["email"] is None and user["company_id"] == company["id"]
    assert (await public_client.get(f"{BASE}/lots/{lot['id']}")).status_code == 404
    assert (await public_client.get(f"{BASE}/lots")).json() == []
    assert (await public_client.get(url)).json()["joined"] is True
    assert (await public_client.get(url)).json()["joinable"] is True

    first_refresh = public_client.cookies.get(REFRESH_COOKIE)
    assert (await join(public_client, url))["id"] == company["id"]
    assert public_client.cookies.get(REFRESH_COOKIE) != first_refresh
    assert (await public_client.get(USER)).json()["id"] == user["id"]

    new_url = await issue_url(req, base)
    assert new_url != url and (await public_client.post(url + "/join")).status_code == 404
    assert (await public_client.get(new_url)).json()["joined"] is True
    assert (await join(public_client, new_url))["id"] == company["id"]
    row = await db.scalar(select(WorkflowInquiryReplyLink))
    assert row.guest_company_id == UUID(company["id"])
    assert await db.get(WorkflowFacilityAccount, facility["facility_key"]) is None

    response = await public_client.patch(COMPANY, json={"profile_version": 1, "site_name": "수정"})
    assert response.status_code == 403
    assert (await public_client.patch(COMPANY, json={"site_name": "수정"})).status_code == 403
    response = await public_client.post(USER + "/withdraw", json={"confirm": True})
    assert response.status_code == 403
    assert (await public_client.get(COMPANY)).json() == company


async def test_revocation_ends_all_sessions_and_reissue_allows_login(inquiry, public_client):
    req, lot, body, base, _ = inquiry
    url = await issue_url(req, base)
    company = await join(public_client, url)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as second:
        await join(second, url)
        previous_access = second.cookies.get(ACCESS_COOKIE)
        assert (await second.post(REFRESH)).status_code == 204
        assert second.cookies.get(ACCESS_COOKIE) != previous_access
        assert (await second.get(COMPANY)).status_code == 200
        assert (await req("A", base + "/reply-link", method="DELETE")).status_code == 204
        for guest in (public_client, second):
            assert (await guest.get(COMPANY)).status_code == 401
            assert (await guest.post(REFRESH)).status_code == 401
            assert (await guest.post(url + "/join")).status_code == 404

        response = await req("A", f"/lots/{lot['id']}", method="GET")
        assert candidate(response.json(), body["capability_key"])[1]["recipient"] is None
        new_url = await issue_url(req, base)
        assert (await join(second, new_url))["id"] == company["id"]
        assert (await public_client.post(REFRESH)).status_code == 401
        assert (await second.get(COMPANY)).status_code == 200


@pytest.mark.parametrize("synthetic", [False, True])
async def test_connected_facility_cannot_join(inquiry, db, public_client, synthetic):
    req, lot, body, base, actors = inquiry
    _, facility = candidate(lot, body["capability_key"])
    url = await issue_url(req, base)
    db.add(
        WorkflowFacilityAccount(
            facility_key=facility["facility_key"],
            company_id=UUID(actors["B"][1]),
            synthetic=synthetic,
            verification_reference="합성 테스트 연결",
        )
    )
    await db.commit()
    payload = (await public_client.get(url)).json()
    assert payload["joinable"] is False and payload["joined"] is False
    response = await public_client.post(url + "/join")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ALREADY_CONNECTED"
    assert "set-cookie" not in response.headers
    rendered = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    assert candidate(rendered, body["capability_key"])[1]["recipient"] == {
        "id": actors["B"][1],
        "name": "B",
        "synthetic": synthetic,
        "guest": False,
    }


async def test_guest_offer_does_not_cross_lot_or_candidate(inquiry, setup_flow, public_client):
    req, lot, body, base, _ = inquiry
    _, create, _, _ = setup_flow
    url = await issue_url(req, base)
    await join(public_client, url)
    another_lot = await reviewed(req, await create(role="B"), role="B")
    assert another_lot["id"] != lot["id"]
    key = body["capability_key"]
    assert candidate(another_lot, key)[1]["recipient"] is None
    other = await req(
        "B", f"/lots/{another_lot['id']}/offers", {**body, "revision": another_lot["revision"]}
    )
    assert other.status_code == 409
    alternatives = [
        f["capability_key"]
        for o in lot["review"]["next_step"]["options"]
        for f in o["facilities"]
        if f["capability_key"] != key and f["recipient"] is None
    ]
    response = await req(
        "A", f"/lots/{lot['id']}/offers", {**body, "capability_key": alternatives[0]}
    )
    assert response.status_code == 409


async def test_guest_handoff_through_output_and_next_candidates(
    inquiry, db, public_client, monkeypatch
):
    req, lot, body, base, _ = inquiry
    path = f"/lots/{lot['id']}"
    stored = await db.get(WorkflowLot, UUID(lot["id"]))
    snapshot = {"review": deepcopy(stored.review)}
    option, facility = candidate(snapshot, body["capability_key"])
    coords = {"latitude": 37.25, "longitude": 127.01}
    facility["location"] = coords
    stored.review = snapshot["review"]
    await db.commit()
    url = await issue_url(req, base)
    company = await join(public_client, url)
    assert company["site_latitude"] == coords["latitude"]
    assert company["site_longitude"] == coords["longitude"]
    rendered = (await req("A", path, method="GET")).json()
    recipient = candidate(rendered, body["capability_key"])[1]["recipient"]
    assert recipient == {
        "id": company["id"],
        "name": company["company_name"],
        "synthetic": False,
        "guest": True,
    }

    offered = await req("A", path + "/offers", body)
    assert offered.status_code == 200, offered.text
    offer = offered.json()["offers"][0]
    assert offer["recipient_id"] == company["id"]
    assert (await public_client.get(url)).status_code == 200
    assert (await join(public_client, url, lot_visible=True))["id"] == company["id"]
    assert [item["id"] for item in (await public_client.get(f"{BASE}/lots")).json()] == [lot["id"]]
    offer_path = f"/offers/{offer['id']}"
    read = await public_client.get(BASE + offer_path)
    assert read.status_code == 200
    message = await public_client.post(
        BASE + offer_path + "/messages",
        json={"revision": read.json()["revision"], "text": "시험 물량 반입을 검토했습니다."},
    )
    assert message.status_code == 200, message.text
    decision = await public_client.post(
        BASE + offer_path + "/decision",
        json={
            "revision": message.json()["revision"],
            "accept": True,
            "scope_checked": True,
            "intake_checked": True,
            "note": "합성 물량 수락",
        },
    )
    assert decision.status_code == 200, decision.text
    qr = await req("A", offer_path + "/qr", {"revision": decision.json()["revision"]})
    assert qr.status_code == 200, qr.text
    received = await public_client.post(
        BASE + offer_path + "/receive",
        json={k: qr.json()[k] for k in ("revision", "token")},
    )
    assert received.status_code == 200, received.text
    assert received.json()["current_company_id"] == company["id"]
    assert (await join(public_client, url, lot_visible=True))["id"] == company["id"]
    output = await public_client.post(
        BASE + path + "/output",
        json={
            "revision": received.json()["revision"],
            "state_key": option["output_state"]["key"],
            "mass_kg": 900,
            "condition": "합성 시험 산출물",
            "evidence": "합성 시험 기록",
        },
    )
    assert output.status_code == 200, output.text

    origins = []

    async def distances(result, origin):
        origins.append(origin.model_dump())

    monkeypatch.setattr("app.domains.transport.workflow.enrich_road_distances", distances)
    next_candidates = await public_client.post(
        BASE + path + "/candidates", json={"revision": output.json()["revision"]}
    )
    assert next_candidates.status_code == 200, next_candidates.text
    assert next_candidates.json()["review"]["next_step"]["options"]
    assert origins == [coords]
    assert (await req("A", base + "/reply-link", method="DELETE")).status_code == 204
    assert (await public_client.get(BASE + path)).status_code == 401
    original = (await req("A", path, method="GET")).json()
    assert original["offers"][0]["status"] == "processed"
    assert original["data"]["completed"][0]["company_id"] == company["id"]
    reissued_url = await issue_url(req, base)
    assert (await join(public_client, reissued_url, lot_visible=True))["id"] == company["id"]
