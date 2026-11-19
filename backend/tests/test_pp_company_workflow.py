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
    assert options == {"pe-clean", "pe-shredded-to-pellet", "pe-flake-repelletise"}


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
