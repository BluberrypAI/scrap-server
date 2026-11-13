"""Synthetic company scenarios. No assertion of actual facility permit or acceptance."""

import io
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image

from app.core.security import create_token
from app.domains.auth.cookies import ACCESS_COOKIE
from app.domains.diagnosis.client import get_engine_client
from app.domains.transport.models import WorkflowFacilityAccount, WorkflowOffer
from app.domains.treatment.intake import IntakeBatchResult, IntakeResult, LotReview
from app.domains.treatment.repository import replace_snapshots
from app.domains.users.models import User
from app.domains.wastes.models import Waste
from app.main import app
from tests.conftest import COMPANY_PAYLOAD
from tests.test_diagnosis import FakeEngine
from tests.test_diagnosis_treatment import detail

BASE = "/api/v1/workflow"


def test_runtime_import_resolves_every_foreign_key_without_test_model_imports():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.main; from app.db.base import Base; "
            "assert 'facilities' in {t.name for t in Base.metadata.sorted_tables}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_model_failure_cannot_offer_and_can_retry(setup_flow, monkeypatch):
    req, create, _, _ = setup_flow
    lot = await create()
    available = False
    calls = []

    async def review(packets, settings, *, lot_context=None):
        calls.append(len(packets))
        return IntakeBatchResult(
            results={
                p["capability_key"]: IntakeResult(
                    status="needs_evidence" if available else "model_unavailable",
                    next_check="추가 확인",
                    lot_review=LotReview(
                        status="reviewed" if available else "model_unavailable",
                        observation_method="no_photo",
                    ),
                )
                for p in packets
            }
        )

    monkeypatch.setattr("app.domains.transport.workflow.review_intakes", review)
    body = {"revision": lot["revision"]}
    lot = (await req("A", f"/lots/{lot['id']}/candidates", body)).json()
    capability = next(iter(lot["review"]["results"]))
    assert (
        await req("A", f"/lots/{lot['id']}/offers", {**body, "capability_key": capability})
    ).status_code == 409
    available = True
    lot = (await req("A", f"/lots/{lot['id']}/candidates", body)).json()
    assert all(r["status"] == "needs_evidence" for r in lot["review"]["results"].values())
    assert calls == [3, 3]


@pytest.fixture
async def setup_flow(client, db, monkeypatch):
    actors = {}
    for role in "ABCD":
        user = User(provider="dev", provider_subject=role, email=f"{role}@example.com", name=role)
        db.add(user)
        await db.commit()
        token = create_token(user.id, "access")
        client.cookies.set(ACCESS_COOKIE, token)
        c = await client.post("/api/v1/companies", json={**COMPANY_PAYLOAD, "company_name": role})
        assert c.status_code == 201
        actors[role] = (token, c.json()["id"])
    for facility, role in [("sarom-hwaseong-2", "B"), ("veolia-doksan-hwaseong", "C")]:
        db.add(
            WorkflowFacilityAccount(
                facility_key=facility,
                company_id=uuid.UUID(actors[role][1]),
                synthetic=True,
                verification_reference="synthetic test fixture, not a real company link",
            )
        )
    await db.commit()
    await replace_snapshots(db)
    fake = FakeEngine()
    fake.reply = httpx.Response(200, json=detail())
    app.dependency_overrides[get_engine_client] = fake.client
    packets_seen = []

    async def review(packets, settings, *, lot_context=None):
        packets_seen.append({"packets": packets, "lot_context": lot_context})
        return IntakeBatchResult(
            results={
                p["capability_key"]: IntakeResult(
                    status="needs_evidence",
                    next_check="수신 기업 확인 필요",
                    lot_review=LotReview(
                        status="reviewed",
                        observation_method="isolated_vision"
                        if lot_context and lot_context.get("photos")
                        else "no_photo",
                    ),
                )
                for p in packets
            }
        )

    monkeypatch.setattr("app.domains.transport.workflow.review_intakes", review)

    async def req(role, path, body=None, method="POST", **kwargs):
        client.cookies.set(ACCESS_COOKIE, actors[role][0])
        return await client.request(method, BASE + path, json=body, **kwargs)

    async def create(form="scrap"):
        res = await req(
            "A",
            "/lots",
            {
                "diagnosis_id": "C1",
                "input_form": form,
                "mass_kg": 1000,
                "condition": "합성 테스트 PP, 실제 물량 아님",
            },
        )
        assert res.status_code == 200, res.text
        return res.json()

    yield req, create, actors, packets_seen
    app.dependency_overrides.pop(get_engine_client, None)


async def choose(req, lot, role, facility):
    res = await req(role, f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    assert res.status_code == 200, res.text
    lot = res.json()
    fs = [f for o in lot["review"]["next_step"]["options"] for f in o["facilities"]]
    assert set(lot["review"]["results"]) == {f["capability_key"] for f in fs}
    key = next(f["capability_key"] for f in fs if f["facility_key"] == facility)
    res = await req(
        role, f"/lots/{lot['id']}/offers", {"revision": lot["revision"], "capability_key": key}
    )
    assert res.status_code == 200, res.text
    return res.json()


async def accept_receive(req, lot, sender, receiver):
    oid = lot["offers"][-1]["id"]
    assert (
        await req(sender, f"/offers/{oid}/qr", {"revision": lot["revision"]})
    ).status_code == 403
    denied = await req(
        receiver,
        f"/offers/{oid}/decision",
        {"revision": lot["revision"], "accept": True, "note": "합성 사례 수락"},
    )
    assert denied.status_code == 409
    r = await req(
        receiver,
        f"/offers/{oid}/decision",
        {
            "revision": lot["revision"],
            "accept": True,
            "note": "합성 사례 수락",
            "scope_checked": True,
            "intake_checked": True,
        },
    )
    assert r.status_code == 200, r.text
    lot = r.json()
    qr = await req(sender, f"/offers/{oid}/qr", {"revision": lot["revision"]})
    assert qr.status_code == 200, qr.text
    q = qr.json()
    bad = await req(
        sender, f"/offers/{oid}/receive", {"revision": q["revision"], "token": q["token"]}
    )
    assert bad.status_code == 403
    r = await req(
        receiver, f"/offers/{oid}/receive", {"revision": q["revision"], "token": q["token"]}
    )
    assert r.status_code == 200, r.text
    lot = r.json()
    replay = await req(
        receiver, f"/offers/{oid}/receive", {"revision": lot["revision"], "token": q["token"]}
    )
    assert replay.status_code == 409
    return lot


async def save_output(req, lot, role, state, mass):
    res = await req(
        role,
        f"/lots/{lot['id']}/output",
        {
            "revision": lot["revision"],
            "state_key": state,
            "mass_kg": mass,
            "condition": "합성 산출물 기록",
            "evidence": "TEST-OUTPUT-001",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("chain", [False, True])
async def test_complete_direct_and_two_hops(setup_flow, chain, db):
    req, create, actors, packets = setup_flow
    lot = await create("scrap" if chain else "shredded")
    if chain:
        lot = await choose(req, lot, "A", "sarom-hwaseong-2")
        assert len(lot["offers"]) == 1  # C does not exist before B's observed output
        lot = await accept_receive(req, lot, "A", "B")
        assert (
            await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
        ).status_code == 409
        lot = await save_output(req, lot, "B", "pp-shredded", 950)
        assert (
            await req(
                "B",
                f"/lots/{lot['id']}/finish",
                {
                    "revision": lot["revision"],
                    "reference": "TEST",
                    "intended_use": "테스트",
                    "confirmed": True,
                },
            )
        ).status_code == 409
    lot = await choose(req, lot, "B" if chain else "A", "veolia-doksan-hwaseong")
    lot = await accept_receive(req, lot, "B" if chain else "A", "C")
    lot = await save_output(req, lot, "C", "pp-pellet", 900)
    result = await req(
        "C",
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "TEST-FINISH",
            "intended_use": "가상 사출용 원료",
            "confirmed": True,
        },
    )
    assert result.status_code == 200, result.text
    result = result.json()
    assert result["status"] == "completed"
    waste = await db.get(Waste, uuid.UUID(lot["id"]))
    assert waste.quantity_value == 1000  # original registration stays distinct from yield
    assert len(result["data"]["completed"]) == (2 if chain else 1)
    assert result["data"]["current"]["purity_percent"] is None
    assert (await req("A", f"/lots/{lot['id']}", method="GET")).json()["status"] == "completed"
    assert (await req("D", f"/lots/{lot['id']}", method="GET")).status_code == 404
    assert len(packets) == (2 if chain else 1)
    assert packets[0]["lot_context"]["mass_kg"] == 1000
    if chain:
        assert packets[1]["lot_context"]["mass_kg"] == 950
        assert packets[1]["lot_context"]["state_key"] == "pp-shredded"
        assert packets[1]["lot_context"]["condition"] == "합성 산출물 기록"


async def test_photos_snapshot_is_private_and_invalid_content_rejected(setup_flow):
    req, create, _, packets = setup_flow
    lot = await create()
    path = f"/lots/{lot['id']}/photos"
    assert (
        await req("A", path, files={"file": ("bad.png", b"not an image", "image/png")})
    ).status_code == 422
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(image, format="PNG")
    res = await req("A", path, files={"file": ("synthetic.png", image.getvalue(), "image/png")})
    assert res.status_code == 200, res.text
    lot = res.json()
    photo = lot["photos"][0]
    assert (await req("D", f"/photos/{photo['id']}", method="GET")).status_code == 404
    lot = await choose(req, lot, "A", "sarom-hwaseong-2")
    sent = packets[-1]["lot_context"]
    assert sent["condition"] == "합성 테스트 PP, 실제 물량 아님"
    assert [p["photo_id"] for p in sent["photos"]] == [photo["id"]]
    assert sent["photos"][0]["data_url"].startswith("data:image/jpeg;base64,")
    assert set(sent) == {"state_key", "mass_kg", "purity_percent", "condition", "photos"}
    assert lot["offers"][-1]["data"]["photo_ids"] == [photo["id"]]
    assert (await req("B", f"/photos/{photo['id']}", method="GET")).headers[
        "content-type"
    ] == "image/jpeg"
    assert (
        await req("A", path, files={"file": ("new.png", image.getvalue(), "image/png")})
    ).status_code == 409


async def test_followup_uses_only_current_photos_and_invalidates_review(setup_flow):
    req, create, _, packets = setup_flow
    lot = await create()
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(image, format="PNG")

    async def photo(role, lot):
        return (
            await req(
                role,
                f"/lots/{lot['id']}/photos",
                files={"file": ("test.png", image.getvalue(), "image/png")},
            )
        ).json()

    lot = await photo("A", lot)
    original_id = lot["photos"][0]["id"]
    lot = await choose(req, lot, "A", "sarom-hwaseong-2")
    lot = await accept_receive(req, lot, "A", "B")
    lot = await save_output(req, lot, "B", "pp-shredded", 950)
    lot = (await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    assert packets[-1]["lot_context"]["photos"] == []
    lot = await photo("B", lot)
    assert lot["review"] is None
    lot = await choose(req, lot, "B", "veolia-doksan-hwaseong")
    ids = [p["photo_id"] for p in packets[-1]["lot_context"]["photos"]]
    assert len(ids) == 1 and original_id not in ids
    assert packets[-1]["lot_context"]["mass_kg"] == 950


async def test_missing_lot_review_blocks_offer_despite_public_evidence(setup_flow, monkeypatch):
    req, create, _, _ = setup_flow
    lot = await create()

    async def review(packets, settings, **kwargs):
        return IntakeBatchResult(
            results={
                p["capability_key"]: IntakeResult(
                    status="reviewed", finding="form_mentioned", next_check="공개 근거만 확인"
                )
                for p in packets
            }
        )

    monkeypatch.setattr("app.domains.transport.workflow.review_intakes", review)
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    key = next(iter(lot["review"]["results"]))
    assert (
        await req(
            "A", f"/lots/{lot['id']}/offers", {"revision": lot["revision"], "capability_key": key}
        )
    ).status_code == 409


async def test_legacy_visual_review_is_not_reused_or_offered(setup_flow, db):
    from app.domains.transport.models import WorkflowLot

    req, create, _, calls = setup_flow
    lot = await create()
    path = f"/lots/{lot['id']}"
    body = {"revision": lot["revision"]}
    lot = (await req("A", path + "/candidates", body)).json()
    key = next(iter(lot["review"]["results"]))
    saved = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    legacy = dict(saved.review)
    legacy.pop("analysis_version")
    saved.review = legacy
    await db.commit()
    assert (await req("A", path + "/offers", {**body, "capability_key": key})).status_code == 409
    count = len(calls)
    fresh = (await req("A", path + "/candidates", body)).json()
    assert len(calls) == count + 1
    assert fresh["review"]["version"] == "lot-vision-v1"  # Existing web contract.
    assert fresh["review"]["analysis_version"] == "isolated-vision-v2"


async def test_old_ai_response_without_observation_method_cannot_offer(setup_flow, monkeypatch):
    req, create, _, _ = setup_flow
    lot = await create()
    calls = []

    async def old_ai(packets, settings, **kwargs):
        calls.append(True)
        return IntakeBatchResult(
            results={
                p["capability_key"]: IntakeResult(
                    status="reviewed",
                    finding="form_mentioned",
                    next_check="공개 근거 확인",
                    lot_review=LotReview(status="reviewed"),
                )
                for p in packets
            }
        )

    monkeypatch.setattr("app.domains.transport.workflow.review_intakes", old_ai)
    path = f"/lots/{lot['id']}"
    body = {"revision": lot["revision"]}
    for _ in range(2):
        lot = (await req("A", path + "/candidates", body)).json()
    assert len(calls) == 2
    key = next(iter(lot["review"]["results"]))
    assert (await req("A", path + "/offers", {**body, "capability_key": key})).status_code == 409


async def test_rejection_revision_and_mismatched_output_hold(setup_flow):
    req, create, _, _ = setup_flow
    lot = await choose(req, await create(), "A", "sarom-hwaseong-2")
    oid = lot["offers"][-1]["id"]
    assert (
        await req(
            "B",
            f"/offers/{oid}/decision",
            {"revision": lot["revision"] - 1, "accept": False, "note": "현재 처리 불가"},
        )
    ).status_code == 409
    lot = (
        await req(
            "B",
            f"/offers/{oid}/decision",
            {"revision": lot["revision"], "accept": False, "note": "현재 처리 불가"},
        )
    ).json()
    assert lot["status"] == "ready"
    lot = await choose(req, lot, "A", "sarom-hwaseong-2")
    lot = await accept_receive(req, lot, "A", "B")
    lot = await save_output(req, lot, "B", "pp-pellet", 900)
    assert lot["status"] == "review_required"
    assert (
        await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    ).status_code == 409
    assert (
        await req(
            "B",
            f"/lots/{lot['id']}/finish",
            {
                "revision": lot["revision"],
                "reference": "TEST",
                "intended_use": "테스트",
                "confirmed": True,
            },
        )
    ).status_code == 409


async def test_qr_expiry_and_reissue(setup_flow, db):
    req, create, _, _ = setup_flow
    lot = await choose(req, await create(), "A", "sarom-hwaseong-2")
    oid = lot["offers"][-1]["id"]
    lot = (
        await req(
            "B",
            f"/offers/{oid}/decision",
            {
                "revision": lot["revision"],
                "accept": True,
                "note": "합성 수락",
                "scope_checked": True,
                "intake_checked": True,
            },
        )
    ).json()
    q1 = (await req("A", f"/offers/{oid}/qr", {"revision": lot["revision"]})).json()
    q2 = (await req("A", f"/offers/{oid}/qr", {"revision": q1["revision"]})).json()
    assert (
        await req("B", f"/offers/{oid}/receive", {"revision": q2["revision"], "token": q1["token"]})
    ).status_code == 403
    row = await db.get(WorkflowOffer, uuid.UUID(oid))
    row.qr_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert (
        await req("B", f"/offers/{oid}/receive", {"revision": q2["revision"], "token": q2["token"]})
    ).status_code == 403
