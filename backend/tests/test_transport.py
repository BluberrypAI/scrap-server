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
    conflict = await client.put(path, json={**body, "destination": "C"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "HANDOFF_ALREADY_REGISTERED"
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
    mismatch = await client.post(path + "/events", json=event)
    assert mismatch.status_code == 403
    assert mismatch.json()["code"] == "RECIPIENT_MISMATCH"
    assert (await client.get(case_path)).status_code == 404
    await login("b")
    assert (await client.get(case_path)).json()["can_process"]
    after = {**snapshot, "pending": None, "completed": [pending]}
    rejected = await client.patch(case_path, json={"revision": 1, "snapshot": after})
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "CASE_UPDATE_REJECTED"
    assert (await client.post(path + "/events", json=event)).status_code == 200
    accepted = (await client.get(case_path)).json()
    waiting = accepted["snapshot"]
    waiting["pending"]["outputUnconfirmedAt"] = "requested"
    deferred = await client.patch(case_path, json={"revision": 1, "snapshot": waiting})
    assert deferred.status_code == 200, deferred.text
    await login("a")
    visible = (await client.get(case_path)).json()
    assert not visible["can_process"] and visible["snapshot"]["pending"]["outputUnconfirmedAt"]
    await login("b")
    assert (
        await client.patch(case_path, json={"revision": 2, "snapshot": after})
    ).status_code == 200
    assert (
        await client.patch(case_path, json={"revision": 2, "snapshot": after})
    ).status_code == 409
    stored = (await client.get(case_path)).json()
    snapshot = stored["snapshot"]
    recorded = {
        **snapshot["completed"][-1],
        "observedOutput": {"state_key": "pp-shredded", "mass_kg": None, "purity_percent": None},
        "observedLabel": "PP 파쇄품",
    }
    payload = {"revision": stored["revision"], "snapshot": {**snapshot, "completed": [recorded]}}
    result = await client.patch(case_path, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["snapshot"]["completed"][-1]["observedOutput"]["mass_kg"] is None
    recorded["observedOutput"]["mass_kg"] = 850
    payload["revision"] = result.json()["revision"]
    result = await client.patch(case_path, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["snapshot"]["completed"][-1]["observedOutput"]["mass_kg"] == 850
    recorded["observedOutput"]["mass_kg"] = 900
    payload["revision"] = result.json()["revision"]
    assert (await client.patch(case_path, json=payload)).status_code == 409


@pytest.mark.parametrize("production", [False, True])
async def test_unverified_treatment_cannot_create_handoff_even_with_client_claim(
    auth_client, user, monkeypatch, production
):
    if production:
        settings = get_settings()
        monkeypatch.setattr(settings, "app_env", "prod")
        monkeypatch.setattr(
            settings, "transport_demo_facilities", {"unverified-site": str(user.id)}
        )
    key = uuid4()
    path = f"/api/v1/transport/{key}"
    response = await auth_client.put(
        path,
        json={
            "lot": "test-lot",
            "origin": "A",
            "destination": "Unverified",
            "destination_key": "unverified-site",
            "case_update": {
                "revision": 0,
                "snapshot": {
                    "version": 1,
                    "id": "test-lot",
                    "name": "PP",
                    "input": {},
                    "completed": [],
                    "pending": {
                        "legId": str(key),
                        "facility": "Unverified",
                        "facility_key": "unverified-site",
                        "source": {"reviewBasis": "operator-confirmed", "reviewReference": "123"},
                    },
                },
            },
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "HANDOFF_EVIDENCE_REQUIRED"
    assert (await auth_client.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_inbox_falls_back_to_lot_id_without_name(auth_client, db, user):
    # 표시용 이름이 빠진 기록이 있어도 인박스 전체가 깨지지 않아야 함
    from app.domains.transport.models import TransportSharedCase

    db.add(
        TransportSharedCase(
            id=uuid4(),
            owner_id=user.id,
            active_id=user.id,
            snapshot={"version": 1, "id": "lot-without-name", "input": {}, "completed": []},
        )
    )
    await db.commit()
    response = await auth_client.get("/api/v1/transport/inbox")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "lot-without-name"
