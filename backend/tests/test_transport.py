from uuid import uuid4

import pytest

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_qr_reads_and_records_on_a_separate_client(client):
    path = f"/api/v1/transport/{uuid4()}"
    body = {"lot": "test-lot", "origin": "A", "destination": "B"}
    assert (await client.put(path, json=body)).status_code == 401
    assert (await client.get(path)).status_code == 404
    login = await client.post("/api/v1/auth/dev-login", json={"email": "transport@example.com"})
    assert login.status_code == 200
    assert (await client.put(path, json=body)).status_code == 200
    assert (await client.put(path, json=body)).status_code == 200
    assert (await client.put(path, json={**body, "destination": "C"})).status_code == 409
    client.cookies.clear()
    pickup = await client.post(path + "/events", json={"role": "driver", "actor": "기사"})
    assert pickup.json()["pickup_actor"] == "기사" and pickup.json()["receipt_at"] is None
    receipt = await client.post(path + "/events", json={"role": "recipient", "actor": "입고"})
    assert receipt.json()["receipt_actor"] == "입고"
    await client.post(path + "/events", json={"role": "recipient", "actor": "변경"})
    assert (await client.get(path)).json() == receipt.json()


@pytest.mark.asyncio
async def test_bound_recipient_has_card_and_only_assigned_account_can_receive(client, monkeypatch):
    async def login(letter):
        response = await client.post(
            "/api/v1/auth/dev-login", json={"email": f"case-{letter}@example.com"}
        )
        assert response.status_code == 200
        return response.json()["user_id"]

    recipient = await login("b")
    monkeypatch.setattr(get_settings(), "transport_demo_facilities", {"test-b": recipient})
    await login("a")
    leg = uuid4()
    path = f"/api/v1/transport/{leg}"
    case_path = f"/api/v1/transport/cases/{leg}"
    pending = {
        "legId": str(leg),
        "facility": "B",
        "facility_key": "test-b",
        "transition_key": "sort",
    }
    snapshot = {
        "version": 1,
        "id": "test-lot",
        "name": "PP 테스트",
        "input": {},
        "pending": pending,
        "completed": [],
    }
    registered = await client.put(
        path,
        json={
            "lot": "test-lot",
            "origin": "A",
            "destination": "B",
            "destination_key": "test-b",
            "case_update": {"revision": 0, "snapshot": snapshot},
        },
    )
    assert registered.status_code == 200 and registered.json()["account_required"]
    assert not (await client.get(case_path)).json()["can_process"]
    event = {"role": "recipient", "actor": "테스트"}
    await login("c")
    assert (await client.post(path + "/events", json=event)).status_code == 403
    assert (await client.get(case_path)).status_code == 404
    await login("b")
    assert (await client.get(case_path)).json()["can_process"]
    after = {**snapshot, "pending": None, "completed": [pending]}
    assert (
        await client.patch(case_path, json={"revision": 1, "snapshot": after})
    ).status_code == 409
    assert (await client.post(path + "/events", json=event)).status_code == 200
    assert (
        await client.patch(case_path, json={"revision": 1, "snapshot": after})
    ).status_code == 200
    assert (
        await client.patch(case_path, json={"revision": 1, "snapshot": after})
    ).status_code == 409
