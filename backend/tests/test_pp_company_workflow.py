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
        encoding="utf-8",
        errors="replace",
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
    assert calls == [len(lot["review"]["results"])] * 2
    assert calls[0] >= 6


@pytest.mark.parametrize("timeout_retry", [False, True])
async def test_partial_review_retries_only_failed_candidates(
    setup_flow, monkeypatch, timeout_retry
):
    req, create, _, _ = setup_flow
    lot = await create()
    calls = []

    async def review(packets, settings, *, lot_context=None):
        keys = [p["capability_key"] for p in packets]
        calls.append(keys)
        if timeout_retry and len(calls) == 3:
            import asyncio

            await asyncio.sleep(1)
        failed = set(keys[-2:]) if len(calls) == 1 else set()
        return IntakeBatchResult(
            results={
                key: IntakeResult(
                    status="model_unavailable" if key in failed else "needs_evidence",
                    next_check="수신 기업 확인 필요",
                    lot_review=LotReview(
                        status="model_unavailable" if key in failed else "reviewed",
                        observation_method="no_photo",
                    ),
                )
                for key in keys
            }
        )

    monkeypatch.setattr("app.domains.transport.workflow.review_intakes", review)
    if timeout_retry:
        monkeypatch.setattr("app.domains.transport.workflow.PARTIAL_RETRY_TIMEOUT", 0.05)
    body = {"revision": lot["revision"]}
    first = (await req("A", f"/lots/{lot['id']}/candidates", body)).json()
    second = (await req("A", f"/lots/{lot['id']}/candidates", body)).json()
    assert calls[1:] == [[key] for key in calls[0][-2:]]
    assert set(second["review"]["results"]) == set(calls[0])
    for key in calls[0][:-2]:
        assert first["review"]["results"][key] == second["review"]["results"][key]
    if timeout_retry:
        assert second["review"]["results"][calls[0][-1]]["status"] == "model_unavailable"
        assert second["review"]["results"][calls[0][-2]]["lot_review"]["status"] == "reviewed"
        return
    assert all(
        r["lot_review"]["status"] == "reviewed" for r in second["review"]["results"].values()
    )
    await req("A", f"/lots/{lot['id']}/candidates", body)
    assert len(calls) == 3


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

    async def create(form="scrap", *, role="A"):
        res = await req(
            role,
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


async def pet_processing(setup_flow, db):
    req, create, actors, _ = setup_flow
    await use_handoff(
        db,
        actors,
        "pet",
        "51-03-01",
        [
            ("saerom-hwaseong-one", "B"),
            ("dy-pyeongtaek", "C"),
        ],
    )
    lot = await choose(req, await create("bottle"), "A", "saerom-hwaseong-one")
    return req, await accept_receive(req, lot, "A", "B")


def combined_output(lot, state="pet-flake", action="hold", **changes):
    return {
        "revision": lot["revision"],
        "state_key": state,
        "mass_kg": 90,
        "condition": "합성 PET 처리 결과",
        "evidence": "TEST-OUTPUT-DISPOSITION",
        "next_action": action,
        **(
            {"intended_use": "시험 재생 원료", "completion_confirmed": True}
            if action == "complete"
            else {}
        ),
        **changes,
    }


@pytest.mark.parametrize(
    "action,status", [("complete", "completed"), ("forward", "processed"), ("hold", "stored")]
)
@pytest.mark.parametrize(
    "material,code,form,site,state",
    [
        ("pp", "51-03-01", "shredded", "hcr-paju", "pp-pellet"),
        ("pe", "51-03-01", "shredded", "hcr-paju", "pe-pellet"),
        ("pet", "51-03-01", "bottle", "saerom-hwaseong-one", "pet-flake"),
        ("aluminium", "51-29-03", "can", "novelis-yeongju", "al-sheet"),
    ],
)
async def test_output_and_disposition_are_saved_together(
    setup_flow, db, action, status, material, code, form, site, state
):
    from sqlalchemy import func, select

    from app.domains.wastes.models import WasteCompletionSnapshot

    req, create, actors, _ = setup_flow
    await use_handoff(db, actors, material, code, [(site, "B")])
    lot = await accept_receive(req, await choose(req, await create(form), "A", site), "A", "B")
    response = await req(
        "B", f"/lots/{lot['id']}/output", combined_output(lot, state=state, action=action)
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == status
    assert saved["data"]["current"]["next_action"] == action
    assert len(saved["data"]["completed"]) == 1
    assert saved["data"]["current"]["purity_percent"] is None
    assert await db.scalar(select(func.count()).select_from(WasteCompletionSnapshot)) == int(
        action == "complete"
    )
    if action == "hold":
        assert (
            await req("B", f"/lots/{lot['id']}/candidates", {"revision": saved["revision"]})
        ).status_code == 409
        assert (
            await req("B", f"/lots/{lot['id']}/review-jobs", {"revision": saved["revision"]})
        ).status_code == 409


@pytest.mark.parametrize(
    "changes",
    [{"state_key": "pet-pellet"}, {"completion_confirmed": False}, {"intended_use": None}],
)
async def test_invalid_combined_completion_does_not_partially_record_output(
    setup_flow, db, changes
):
    req, lot = await pet_processing(setup_flow, db)
    response = await req(
        "B", f"/lots/{lot['id']}/output", combined_output(lot, action="complete", **changes)
    )
    assert response.status_code == 409
    saved = (await req("B", f"/lots/{lot['id']}", method="GET")).json()
    assert saved["status"] == "processing"
    assert saved["revision"] == lot["revision"]
    assert saved["data"]["completed"] == []
    assert saved["data"]["current"]["state_key"] == "pet-bottle"


async def test_nonterminal_output_cannot_complete_and_hold_can_resume(setup_flow, db):
    req, create, _, _ = setup_flow
    lot = await accept_receive(
        req, await choose(req, await create(), "A", "sarom-hwaseong-2"), "A", "B"
    )
    response = await req(
        "B",
        f"/lots/{lot['id']}/output",
        combined_output(lot, state="pp-shredded", action="complete"),
    )
    assert response.status_code == 409
    response = await req(
        "B", f"/lots/{lot['id']}/output", combined_output(lot, state="pp-shredded")
    )
    assert response.status_code == 200, response.text
    stored = response.json()
    assert stored["status"] == "stored"
    denied = await req(
        "B",
        f"/lots/{lot['id']}/output-action",
        {
            "revision": stored["revision"],
            "next_action": "complete",
            "intended_use": "시험 재생 원료",
            "completion_confirmed": True,
        },
    )
    assert denied.status_code == 409
    unchanged = (await req("B", f"/lots/{lot['id']}", method="GET")).json()
    assert unchanged["status"] == "stored"
    assert unchanged["revision"] == stored["revision"]
    assert unchanged["data"]["current"]["next_action"] == "hold"
    denied = await req(
        "A",
        f"/lots/{lot['id']}/output-action",
        {"revision": stored["revision"], "next_action": "forward"},
    )
    assert denied.status_code == 403
    denied = await req(
        "B",
        f"/lots/{lot['id']}/output-action",
        {"revision": stored["revision"] - 1, "next_action": "forward"},
    )
    assert denied.status_code == 409
    resumed = await req(
        "B",
        f"/lots/{lot['id']}/output-action",
        {"revision": stored["revision"], "next_action": "forward"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "processed"
    assert len(resumed.json()["data"]["completed"]) == 1


async def test_late_recipient_binding_updates_cached_candidates_without_ai_rerun(
    setup_flow, db, monkeypatch
):
    from app.core.config import get_settings
    from app.domains.companies.models import Company
    from app.domains.transport.models import WorkflowLot

    req, create, actors, packets = setup_flow
    lot = await create("shredded")
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()

    def target(value):
        return next(
            f
            for o in value["review"]["next_step"]["options"]
            for f in o["facilities"]
            if f["facility_key"] == "hcr-paju"
        )

    assert target(lot)["recipient"] is None
    binding = WorkflowFacilityAccount(
        facility_key="hcr-paju",
        company_id=uuid.UUID(actors["D"][1]),
        synthetic=True,
        verification_reference="synthetic account linked after AI review",
    )
    db.add(binding)
    await db.commit()
    fresh = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    assert target(fresh)["recipient"] == {
        "id": actors["D"][1],
        "name": "D",
        "synthetic": True,
        "guest": False,
    }
    assert fresh["revision"] == lot["revision"] and len(packets) == 1
    stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    assert target({"review": stored.review})["recipient"] is None
    company = await db.get(Company, uuid.UUID(actors["D"][1]))
    company.company_name = "새 수신 기업명"
    await db.commit()
    fresh = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    assert target(fresh)["recipient"]["name"] == "새 수신 기업명"
    binding.company_id = uuid.UUID(actors["A"][1])
    await db.commit()
    assert target((await req("A", f"/lots/{lot['id']}", method="GET")).json())["recipient"] is None
    binding.company_id = uuid.UUID(actors["D"][1])
    await db.commit()
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    monkeypatch.setattr(get_settings(), "demo_facility_bindings", False)
    assert target((await req("A", f"/lots/{lot['id']}", method="GET")).json())["recipient"] is None
    monkeypatch.setattr(get_settings(), "app_env", "test")
    await db.delete(binding)
    await db.commit()
    assert target((await req("A", f"/lots/{lot['id']}", method="GET")).json())["recipient"] is None
    assert len(packets) == 1


@pytest.mark.parametrize("finish_at_b", [False, True])
async def test_stored_pet_can_continue_to_c_or_complete_without_new_output_step(
    setup_flow, db, finish_at_b
):
    from sqlalchemy import func, select

    from app.domains.wastes.models import WasteCompletionSnapshot

    req, lot = await pet_processing(setup_flow, db)
    stored = (await req("B", f"/lots/{lot['id']}/output", combined_output(lot))).json()
    if finish_at_b:
        response = await req(
            "B",
            f"/lots/{lot['id']}/output-action",
            {
                "revision": stored["revision"],
                "next_action": "complete",
                "intended_use": "시험 재생 원료",
                "completion_confirmed": True,
            },
        )
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["status"] == "completed" and len(saved["data"]["completed"]) == 1
        assert await db.scalar(select(func.count()).select_from(WasteCompletionSnapshot)) == 1
        return
    resumed = await req(
        "B",
        f"/lots/{lot['id']}/output-action",
        {"revision": stored["revision"], "next_action": "forward"},
    )
    lot = await accept_receive(
        req, await choose(req, resumed.json(), "B", "dy-pyeongtaek"), "B", "C"
    )
    response = await req(
        "C",
        f"/lots/{lot['id']}/output",
        combined_output(lot, state="pet-pellet", action="complete", mass_kg=85),
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == "completed" and len(saved["data"]["completed"]) == 2
    assert await db.scalar(select(func.count()).select_from(WasteCompletionSnapshot)) == 1
    assert (
        await req(
            "C",
            f"/lots/{lot['id']}/output-action",
            {"revision": saved["revision"], "next_action": "hold"},
        )
    ).status_code == 409


async def test_dispatch_requires_sender_acceptance_and_preserves_qr_receipt(setup_flow):
    req, create, actors, _ = setup_flow
    lot = await choose(req, await create("shredded"), "A", "veolia-doksan-hwaseong")
    oid = lot["offers"][-1]["id"]
    path = f"/offers/{oid}/dispatch"
    assert (await req("A", path, {"revision": lot["revision"]})).status_code == 409
    lot = (
        await req(
            "C",
            f"/offers/{oid}/decision",
            {
                "revision": lot["revision"],
                "accept": True,
                "note": "합성 시연 수락",
                "scope_checked": True,
                "intake_checked": True,
            },
        )
    ).json()
    assert (await req("C", path, {"revision": lot["revision"]})).status_code == 403
    assert (await req("A", path, {"revision": lot["revision"] - 1})).status_code == 409
    result = await req("A", path, {"revision": lot["revision"]})
    assert result.status_code == 200, result.text
    lot = result.json()
    assert lot["current_company_id"] == actors["A"][1]
    assert lot["offers"][-1]["data"]["dispatch"]["company_id"] == actors["A"][1]
    assert not lot["offers"][-1]["can_dispatch"]
    assert (await req("A", path, {"revision": lot["revision"]})).status_code == 409
    qr = (await req("A", f"/offers/{oid}/qr", {"revision": lot["revision"]})).json()
    receipt = await req(
        "C",
        f"/offers/{oid}/receive",
        {
            "revision": qr["revision"],
            "token": qr["token"],
        },
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["current_company_id"] == actors["C"][1]
    assert receipt.json()["status"] == "processing"


@pytest.mark.parametrize("chain", [False, True])
async def test_complete_direct_and_two_hops(setup_flow, chain, db, monkeypatch):
    req, create, actors, packets = setup_flow
    from app.domains.companies.models import Company
    from app.domains.treatment.road_distance import enrich_road_distances
    from tests.test_recycling_handoff import with_recycling

    origins = []
    for role, lat, lon in [("A", 37.16, 126.9), ("B", 37.22, 126.97)]:
        company = await db.get(Company, uuid.UUID(actors[role][1]))
        company.site_latitude, company.site_longitude = lat, lon
    await db.commit()

    async def capture_distance_origin(result, origin):
        origins.append((origin.latitude, origin.longitude))
        return await enrich_road_distances(result, origin)

    monkeypatch.setattr(
        "app.domains.transport.workflow.enrich_road_distances", capture_distance_origin
    )
    fake = FakeEngine()
    fake.reply = httpx.Response(200, json=with_recycling())
    app.dependency_overrides[get_engine_client] = fake.client
    lot = await create("scrap" if chain else "shredded")
    assert lot["data"]["recycling"]["types"]["analysis"] == ["R-8-1", "R-10"]
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
    for packet in packets[0]["packets"]:
        assert packet["recycling_types"]["analysis"] == ["R-8-1", "R-10"]
        assert packet["recycling_basis"]["source_url"].startswith("https://www.law.go.kr/")
    if chain:
        for packet in packets[-1]["packets"]:
            assert packet["recycling_types"] == {} and packet["waste_code"] is None
            assert "recycling_basis" not in packet

    assert (await req("A", f"/lots/{lot['id']}", method="GET")).json()["status"] == "completed"
    assert (await req("D", f"/lots/{lot['id']}", method="GET")).status_code == 404
    assert len(packets) == (2 if chain else 1)
    assert origins == ([(37.16, 126.9), (37.22, 126.97)] if chain else [(37.16, 126.9)])
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


@pytest.mark.parametrize("missing", ["analysis_version", "recycling_checksum"])
async def test_legacy_visual_review_is_not_reused_or_offered(setup_flow, db, missing):
    from app.domains.transport.models import WorkflowLot

    req, create, _, calls = setup_flow
    lot = await create()
    path = f"/lots/{lot['id']}"
    body = {"revision": lot["revision"]}
    lot = (await req("A", path + "/candidates", body)).json()
    key = next(iter(lot["review"]["results"]))
    saved = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    legacy = dict(saved.review)
    legacy.pop(missing)
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


async def test_current_company_can_correct_mismatched_last_output(setup_flow):
    req, create, _, _ = setup_flow
    lot = await accept_receive(
        req, await choose(req, await create(), "A", "sarom-hwaseong-2"), "A", "B"
    )
    mismatched = await save_output(req, lot, "B", "pp-pellet", 900)
    assert mismatched["status"] == "review_required"
    expected = mismatched["data"]["completed"][-1]["expected_state"]
    path = f"/lots/{lot['id']}/output-correction"
    body = {
        "revision": mismatched["revision"],
        "state_key": expected,
        "mass_kg": 880,
        "condition": "실제 작업 기록을 다시 확인한 산출물",
        "evidence": "TEST-CORRECTED-001",
        "next_action": "hold",
        "reason": "산출물 형태를 잘못 선택해 정정합니다.",
    }
    assert (await req("A", path, body)).status_code == 403
    assert (await req("B", path, {**body, "revision": body["revision"] - 1})).status_code == 409
    still_mismatched = await req("B", path, {**body, "state_key": "pp-pellet"})
    assert still_mismatched.status_code == 200, still_mismatched.text
    assert still_mismatched.json()["status"] == "review_required"
    body["revision"] = still_mismatched.json()["revision"]
    corrected = await req("B", path, body)
    assert corrected.status_code == 200, corrected.text
    saved = corrected.json()
    assert saved["status"] == "stored"
    assert saved["review"] is None
    assert len(saved["data"]["completed"]) == 1
    assert saved["data"]["current"]["state_key"] == expected
    assert saved["data"]["completed"][-1]["output"]["mass_kg"] == 880
    correction = [
        event for event in saved["data"]["events"] if event["action"] == "처리 결과 정정"
    ][-1]
    assert correction["before"]["state_key"] == "pp-pellet"
    assert correction["after"]["state_key"] == expected
    assert correction["reason"] == body["reason"]
    assert (await req("B", path, {**body, "revision": saved["revision"]})).status_code == 409


async def test_current_site_location_hides_old_missing_coordinate_warning(setup_flow, db):
    from app.domains.companies.models import Company
    from app.domains.transport.models import WorkflowLot

    req, create, actors, _ = setup_flow
    lot = await create()
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    warning = "사업장 좌표가 없어 거리 순위는 표시하지 않습니다."
    row.data = {**row.data, "warnings": [warning, "인계 전 물량 확인 필요"]}
    await db.commit()
    before = await req("A", f"/lots/{lot['id']}", method="GET")
    assert warning in before.json()["data"]["warnings"]
    company = await db.get(Company, uuid.UUID(actors["A"][1]))
    company.site_latitude = 37.452798
    company.site_longitude = 127.1337775
    await db.commit()
    warnings = (await req("A", f"/lots/{lot['id']}", method="GET")).json()["data"]["warnings"]
    assert warnings == ["인계 전 물량 확인 필요"]


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


async def use_handoff(db, actors, material, code, bindings=()):
    """다른 재질의 확정 문진으로 바꾸고, 필요한 업체를 합성 계정에 연결함."""
    for facility, role in bindings:
        db.add(
            WorkflowFacilityAccount(
                facility_key=facility,
                company_id=uuid.UUID(actors[role][1]),
                synthetic=True,
                verification_reference="synthetic test fixture, not a real company link",
            )
        )
    await db.commit()
    d = detail()
    d["handoff"].update(
        waste_code=code,
        facts={"material": {"value": material}, "physical_state": {"value": "solid"}},
    )
    fake = FakeEngine()
    fake.reply = httpx.Response(200, json=d)
    app.dependency_overrides[get_engine_client] = fake.client


@pytest.mark.parametrize(
    "material,code,form,first_site,first_transition,output,second_site,second_transition,final",
    [
        (
            "pp",
            "51-03-01",
            "scrap",
            "sarom-hwaseong-2",
            "pp-prepare",
            "pp-shredded",
            "hcr-paju",
            "pp-flake-repelletise",
            "pp-pellet",
        ),
        (
            "pe",
            "51-03-01",
            "film",
            "sarom-hwaseong-2",
            "pe-prepare",
            "pe-shredded",
            "hcr-paju",
            "pe-flake-repelletise",
            "pe-pellet",
        ),
        (
            "pet",
            "51-03-07",
            "bottle",
            "samyang-sihwa",
            "pet-bottle-to-flake",
            "pet-flake",
            "bgf-yesan",
            "pet-pelletise",
            "pet-pellet",
        ),
        (
            "ferrous",
            "51-29-01",
            "scrap",
            "dongyang-gwangju",
            "ferrous-shear",
            "ferrous-prepared",
            "hyundai-incheon",
            "ferrous-prepared-eaf-billet",
            "ferrous-billet",
        ),
        (
            "aluminium",
            "51-29-03",
            "can",
            "hyundai-resource-hwaseong",
            "al-can-prepare",
            "al-scrap",
            "jmtech-gimpo",
            "al-scrap-to-granule",
            "al-granule",
        ),
    ],
)
async def test_each_material_followup_uses_current_owner_road_origin(
    setup_flow,
    db,
    monkeypatch,
    material,
    code,
    form,
    first_site,
    first_transition,
    output,
    second_site,
    second_transition,
    final,
):
    """Authenticated A→B→C, synthetic AI/road service; live road matrix is separate."""
    from app.core.config import get_settings
    from app.domains.companies.models import Company
    from app.domains.treatment.road_distance import enrich_road_distances

    req, create, actors, packets = setup_flow
    bindings = [(second_site, "C")]
    if first_site != "sarom-hwaseong-2":
        bindings.append((first_site, "B"))
    await use_handoff(db, actors, material, code, bindings)
    origins = []
    for role, lat, lon in [("A", 37.16, 126.9), ("B", 37.22, 126.97)]:
        company = await db.get(Company, uuid.UUID(actors[role][1]))
        company.site_latitude, company.site_longitude = lat, lon
    await db.commit()
    monkeypatch.setattr(get_settings(), "osrm_demo_enabled", True)

    async def roads(origin, sites, client=None):
        # Deliberately opposite ordering for B: stale A ranking cannot satisfy this test.
        keys = sorted(sites, reverse=origin.latitude > 37.2)
        return {key: (10.0 + i, 600.0 + i) for i, key in enumerate(keys)}

    monkeypatch.setattr("app.domains.treatment.osrm_distance.lookup", roads)

    async def capture(result, origin):
        origins.append((origin.latitude, origin.longitude))
        return await enrich_road_distances(result, origin)

    monkeypatch.setattr("app.domains.transport.workflow.enrich_road_distances", capture)

    async def review_offer(lot, role, site, transition):
        r = await req(role, f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
        assert r.status_code == 200, r.text
        lot = r.json()
        review = lot["review"]
        assert review["origin_company_id"] == actors[role][1]
        assert review["origin"]["latitude"] == (37.16 if role == "A" else 37.22)
        facilities = [f for o in review["next_step"]["options"] for f in o["facilities"]]
        assert set(review["results"]) == {f["capability_key"] for f in facilities}
        unique = {f["facility_key"]: f for f in facilities}
        ranked = sorted(
            (f for f in unique.values() if f["distance_rank"] is not None),
            key=lambda f: f["distance_rank"],
        )
        assert len(ranked) <= 5
        assert all(f["road_distance_status"] == "available" for f in ranked)
        assert [f["road_distance_km"] for f in ranked] == sorted(
            f["road_distance_km"] for f in ranked
        )
        if role == "B":
            assert review["next_step"]["basis"] == "observed_output"
            assert review["next_step"]["current_state"]["key"] == output
        option = next(
            o for o in review["next_step"]["options"] if o["transition_key"] == transition
        )
        key = next(f["capability_key"] for f in option["facilities"] if f["facility_key"] == site)
        r = await req(
            role, f"/lots/{lot['id']}/offers", {"revision": lot["revision"], "capability_key": key}
        )
        assert r.status_code == 200, r.text
        return r.json()

    lot = await create(form)
    lot = await review_offer(lot, "A", first_site, first_transition)
    lot = await accept_receive(req, lot, "A", "B")
    assert (
        await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    ).status_code == 409
    lot = await save_output(req, lot, "B", output, 950)
    lot = await review_offer(lot, "B", second_site, second_transition)
    lot = await accept_receive(req, lot, "B", "C")
    lot = await save_output(req, lot, "C", final, 900)
    r = await req(
        "C",
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "SYNTHETIC-ROAD-TEST",
            "intended_use": "합성 시험용 재생 원료",
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    assert origins == [(37.16, 126.9), (37.22, 126.97)]
    assert packets[-1]["lot_context"]["mass_kg"] == 950
    assert packets[-1]["lot_context"]["state_key"] == output


async def test_aluminium_can_handoff_completes_with_sheet(setup_flow, db):
    req, create, actors, _ = setup_flow
    await use_handoff(db, actors, "aluminium", "51-29-03", [("novelis-yeongju", "B")])
    lot = await create("can")
    assert lot["data"]["current"]["state_key"] == "al-used-can"
    assert (await db.get(Waste, uuid.UUID(lot["id"]))).name == "알루미늄 자원순환"
    lot = await choose(req, lot, "A", "novelis-yeongju")
    lot = await accept_receive(req, lot, "A", "B")
    wrong = await req(
        "B",
        f"/lots/{lot['id']}/output",
        {
            "revision": lot["revision"],
            "state_key": "pp-pellet",
            "mass_kg": 900,
            "condition": "다른 재질 상태",
            "evidence": "TEST",
        },
    )
    assert wrong.status_code == 422
    lot = await save_output(req, lot, "B", "al-sheet", 900)
    assert lot["status"] == "processed"
    done = await req(
        "B",
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "TEST-AL",
            "intended_use": "가상 압연 원료",
            "confirmed": True,
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"


async def test_pe_film_shredded_output_is_not_final(setup_flow, db):
    req, create, actors, _ = setup_flow
    await use_handoff(db, actors, "pe", "51-03-01")
    lot = await create("film")
    assert lot["data"]["current"]["state_key"] == "pe-scrap"
    assert lot["data"]["initial"]["material"] == "pe"
    lot = await choose(req, lot, "A", "sarom-hwaseong-2")
    assert lot["offers"][-1]["data"]["option"]["transition_key"] == "pe-prepare"
    lot = await accept_receive(req, lot, "A", "B")
    lot = await save_output(req, lot, "B", "pe-shredded", 950)
    assert lot["status"] == "processed"
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
    lot = (await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    options = {o["transition_key"] for o in lot["review"]["next_step"]["options"]}
    assert options == {
        "pe-clean",
        "pe-shredded-to-pellet",
        "pe-flake-repelletise",
        "pe-public-pellet-manufacture",
    }


@pytest.mark.parametrize(
    "material, code, form",
    [("pvc", "51-03-01", "wallpaper"), ("eps", "51-03-01", "ingot"), ("pa66", "51-03-08", "net")],
)
async def test_unsupported_material_form_is_rejected(setup_flow, db, material, code, form):
    req, _, actors, _ = setup_flow
    await use_handoff(db, actors, material, code)
    res = await req(
        "A",
        "/lots",
        {"diagnosis_id": "C1", "input_form": form, "mass_kg": 10, "condition": "합성 테스트"},
    )
    assert res.status_code in {409, 422}
