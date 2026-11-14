"""Synthetic actors, deterministic AI stub. This does not certify real facility intake."""

import json
import uuid
from hashlib import sha256

import httpx
import pytest

from app.domains.diagnosis.client import get_engine_client
from app.domains.transport.models import WorkflowFacilityAccount
from app.domains.treatment.repository import replace_snapshots
from app.main import app
from tests.test_diagnosis import FakeEngine
from tests.test_diagnosis_treatment import detail
from tests.test_pp_company_workflow import accept_receive, choose, save_output
from tests.test_pp_company_workflow import setup_flow as _setup_flow
from tests.test_treatment_registry import registry_row

setup_flow = _setup_flow


def test_material_evidence_precedes_generic_equipment_hits():
    from app.domains.treatment.directory import normalize_record, registry_matches
    from app.domains.treatment.schemas import FacilitySearchRequest

    named = registry_row("PP explicit", "PP", "폐기물중간재활용업", "37.17")
    unknown = registry_row("unmapped crusher", "99-99-99", "폐기물중간재활용업", "37.17")
    records = [
        normalize_record(row, i, "national-json", "0" * 64)
        for i, row in enumerate([unknown, named])
    ]
    records[0]["equipment_text"] = "분쇄"
    result, _ = registry_matches(records, "pp", FacilitySearchRequest(transition_key="pp-prepare"))
    assert result[0][0]["name"] == "PP explicit"
    assert result[1][1] == "unmapped_codes_require_review"


async def test_conditional_acceptance_needs_sender_evidence_and_recipient_confirmation(setup_flow):
    req, create, _, _ = setup_flow
    lot = await choose(req, await create(), "A", "sarom-hwaseong-2")
    oid = lot["offers"][-1]["id"]
    payload = {
        "revision": lot["revision"],
        "conditions": ["오염 제거 후 확인 자료", "반입 일정을 확인"],
        "note": "검사 후 조건부 수락",
    }
    assert (await req("A", f"/offers/{oid}/conditions", payload)).status_code == 403
    lot = (await req("B", f"/offers/{oid}/conditions", payload)).json()
    assert lot["status"] == "conditional"
    ids = [c["id"] for c in lot["offers"][-1]["data"]["conditions"]]
    assert (await req("A", f"/offers/{oid}/qr", {"revision": lot["revision"]})).status_code == 403
    approval = {
        "revision": lot["revision"],
        "accept": True,
        "note": "검토 완료함",
        "scope_checked": True,
        "intake_checked": True,
        "resolved_condition_ids": ids,
    }
    assert (await req("B", f"/offers/{oid}/decision", approval)).status_code == 409
    answers = {
        "revision": lot["revision"],
        "responses": {k: "합성 검사자료 TEST-001 확인" for k in ids},
    }
    assert (await req("B", f"/offers/{oid}/condition-responses", answers)).status_code == 403
    lot = (await req("A", f"/offers/{oid}/condition-responses", answers)).json()
    assert lot["status"] == "conditional"  # Submission is not approval.
    approval["revision"] = lot["revision"]
    approval["resolved_condition_ids"] = ids[:1]
    assert (await req("B", f"/offers/{oid}/decision", approval)).status_code == 409
    approval["resolved_condition_ids"] = ids
    lot = (await req("B", f"/offers/{oid}/decision", approval)).json()
    qr = (await req("A", f"/offers/{oid}/qr", {"revision": lot["revision"]})).json()
    lot = (
        await req("B", f"/offers/{oid}/receive", {"revision": qr["revision"], "token": qr["token"]})
    ).json()
    assert lot["status"] == "processing"
    lot = await save_output(req, lot, "B", "pp-shredded", 950)
    lot = await choose(req, lot, "B", "veolia-doksan-hwaseong")
    lot = await accept_receive(req, lot, "B", "C")
    lot = await save_output(req, lot, "C", "pp-pellet", 900)
    r = await req(
        "C",
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "TEST-FINISH",
            "intended_use": "가상 원료 제조",
            "confirmed": True,
        },
    )
    assert r.status_code == 200 and r.json()["status"] == "completed"


async def test_answers_are_scoped_persisted_and_sent_to_ai_without_approval(setup_flow):
    req, create, _, seen = setup_flow
    lot = await create()
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    f = lot["review"]["next_step"]["options"][0]["facilities"][0]
    form = f["intake_conditions"]
    assert form["facts"] and form["recipient_confirmation_required"]
    data = {
        "revision": lot["revision"],
        "capability_key": f["capability_key"],
        "answers": {"contamination": "모름", "packaging": "마대"},
    }
    assert (await req("B", f"/lots/{lot['id']}/intake-answers", data)).status_code == 404
    assert (
        await req(
            "A", f"/lots/{lot['id']}/intake-answers", {**data, "answers": {"unknown-field": "yes"}}
        )
    ).status_code == 422
    lot = (await req("A", f"/lots/{lot['id']}/intake-answers", data)).json()
    assert lot["review"] is None
    assert (await req("A", f"/lots/{lot['id']}/intake-answers", data)).status_code == 409
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    packet = next(p for p in seen[-1]["packets"] if p["capability_key"] == f["capability_key"])
    assert packet["intake_answers"]["contamination: 기름·약품·내용물 등의 오염이 있나요?"] == "모름"
    f = next(
        f2
        for o in lot["review"]["next_step"]["options"]
        for f2 in o["facilities"]
        if f2["capability_key"] == f["capability_key"]
    )
    assert f["intake_conditions"]["assessment"]["dispatch_approved"] is False
    assert "contamination" in f["intake_conditions"]["assessment"]["confirmation_keys"]


async def test_changed_condition_sources_require_re_review_before_offer(setup_flow, monkeypatch):
    from app.domains.treatment.conditions import published_conditions

    req, create, _, seen = setup_flow
    lot = await create()
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    key = next(iter(lot["review"]["results"]))
    changed = {**published_conditions(), "revision_for_test": "new"}
    monkeypatch.setattr("app.domains.transport.workflow.published_conditions", lambda: changed)
    r = await req(
        "A", f"/lots/{lot['id']}/offers", {"revision": lot["revision"], "capability_key": key}
    )
    assert r.status_code == 409
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    assert len(seen) == 2
    assert lot["review"]["conditions_checksum"]


@pytest.mark.parametrize(
    "material,code,form,plan",
    [
        ("pe", "51-03-01", "film", ["pe-prepare", "pe-clean", "pe-pelletise"]),
        ("pet", "51-03-07", "bottle", ["pet-bottle-to-flake", "pet-pelletise"]),
        ("aluminium", "51-29-03", "can", ["al-can-to-ingot"]),
    ],
)
async def test_non_pp_complete_handoffs(setup_flow, db, material, code, form, plan):
    req, _, actors, seen = setup_flow
    fake = FakeEngine()
    payload = detail()
    payload["handoff"]["waste_code"] = code
    payload["handoff"]["facts"]["material"]["value"] = material
    fake.reply = httpx.Response(200, json=payload)
    app.dependency_overrides[get_engine_client] = fake.client
    r = await req(
        "A",
        "/lots",
        {"diagnosis_id": "C1", "input_form": form, "mass_kg": 1000, "condition": "합성 시험 물량"},
    )
    assert r.status_code == 200, r.text
    lot = r.json()
    sender = "A"
    for index, transition in enumerate(plan):
        receiver = "B" if index % 2 == 0 else "C"
        lot = (
            await req(sender, f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
        ).json()
        option = next(
            o for o in lot["review"]["next_step"]["options"] if o["transition_key"] == transition
        )
        f = option["facilities"][0]
        await db.merge(
            WorkflowFacilityAccount(
                facility_key=f["facility_key"],
                company_id=uuid.UUID(actors[receiver][1]),
                synthetic=True,
                verification_reference="synthetic multi-material test, not real approval",
            )
        )
        await db.commit()
        r = await req(
            sender,
            f"/lots/{lot['id']}/offers",
            {"revision": lot["revision"], "capability_key": f["capability_key"]},
        )
        assert r.status_code == 200, r.text
        lot = await accept_receive(req, r.json(), sender, receiver)
        assert (
            await req(
                receiver,
                f"/lots/{lot['id']}/output",
                {
                    "revision": lot["revision"],
                    "state_key": "pp-pellet",
                    "mass_kg": 900,
                    "condition": "잘못된 재질",
                    "evidence": "TEST-001",
                },
            )
        ).status_code == 422
        lot = await save_output(
            req, lot, receiver, option["output_state"]["key"], 1000 - 20 * (index + 1)
        )
        sender = receiver
    r = await req(
        sender,
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "TEST-FINAL",
            "intended_use": "합성 최종 원료",
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    assert all(p["material"] == material for call in seen for p in call["packets"])


async def test_directory_all_pages_remain_leads_and_are_stage_scoped(setup_flow, db, tmp_path):
    req, create, _, _ = setup_flow
    rows = [registry_row(f"test-{i}", "51-03-01", "폐기물중간재활용업", "37.17") for i in range(23)]
    raw = json.dumps(rows).encode()
    file = tmp_path / "registry.json"
    file.write_bytes(raw)
    await replace_snapshots(db, file, sha256(raw).hexdigest())
    lot = await create()
    body = {"revision": lot["revision"], "transition_key": "pp-prepare", "page_size": 7}
    ids = set()
    while True:
        r = await req("A", f"/lots/{lot['id']}/directory", body)
        assert r.status_code == 200, r.text
        page = r.json()
        for row in page["registry_candidates"]:
            assert row["listing_id"] not in ids
            ids.add(row["listing_id"])
            assert not row["research_packet"]["can_request_intake"]
            assert row["research_packet"]["stage_capability"] == "not_established"
        if not page["pagination"]["has_more"]:
            break
        body["cursor"] = page["pagination"]["next_cursor"]
    assert len(ids) == 23
    body.update(transition_key="pe-prepare", cursor=None)
    assert (await req("A", f"/lots/{lot['id']}/directory", body)).status_code == 422

    body.update(transition_key="pp-prepare")
    page = (await req("A", f"/lots/{lot['id']}/directory", body)).json()
    listing = page["registry_candidates"][0]["listing_id"]
    inquiry = {**body, "listing_id": listing, "answers": {"process_evidence": "자료 없음"}}
    path = f"/lots/{lot['id']}/directory-inquiries"
    assert (await req("B", path, inquiry)).status_code == 404
    assert (await req("A", path, {**inquiry, "listing_id": "invented"})).status_code == 422
    assert (await req("A", path, {**inquiry, "answers": {"permit": "yes"}})).status_code == 422
    saved = await req("A", path, inquiry)
    assert saved.status_code == 200, saved.text
    entry = saved.json()["data"]["directory_inquiries"]["0"]["pp-prepare:" + listing]
    assert entry["status"] == "evidence_and_account_required"
    assert entry["dispatch_approved"] is False
    assert entry["intake_conditions"]["answers"]["process_evidence"]["value"] == "자료 없음"
    assert (await req("A", path, inquiry)).status_code == 409


def test_broad_metal_can_requires_explicit_aluminium_form_and_pet_mismatch_stays_blocked():
    from app.domains.diagnosis.schemas import TreatmentSelectionIn
    from app.domains.diagnosis.treatment import context_from_handoff
    from tests.test_diagnosis_treatment import COMPANY

    d = detail()
    d["handoff"]["facts"]["material"]["value"] = "metal_can"
    d["handoff"]["waste_code"] = "51-29-03"
    pending = context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY)
    assert pending.status == "needs_input" and pending.route_input is None
    assert pending.available_forms == [{"value": "can", "label": "사용 후 알루미늄 음료캔"}]
    confirmed = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="can"), COMPANY)
    assert confirmed.status == "ready"
    assert any("폐금속캔 번호만" in w for w in confirmed.warnings)
    d["handoff"]["facts"]["material"]["value"] = "pet"
    d["handoff"]["waste_code"] = "51-03-01"
    assert (
        context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="bottle"), COMPANY).status
        == "unsupported"
    )


@pytest.mark.parametrize("answer", ["예", "모름"])
async def test_explicit_public_exclusion_cannot_be_overridden_by_acceptance(setup_flow, db, answer):
    req, create, actors, _ = setup_flow
    db.add(
        WorkflowFacilityAccount(
            facility_key="jungang-gongju",
            company_id=uuid.UUID(actors["B"][1]),
            synthetic=True,
            verification_reference="synthetic test only",
        )
    )
    await db.commit()
    lot = await create()
    lot = (await req("A", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})).json()
    f = next(
        f
        for o in lot["review"]["next_step"]["options"]
        for f in o["facilities"]
        if f["facility_key"] == "jungang-gongju"
    )
    lot = (
        await req(
            "A",
            f"/lots/{lot['id']}/intake-answers",
            {
                "revision": lot["revision"],
                "capability_key": f["capability_key"],
                "answers": {"designated": answer},
            },
        )
    ).json()
    lot = await choose(req, lot, "A", "jungang-gongju")
    oid = lot["offers"][-1]["id"]
    r = await req(
        "B",
        f"/offers/{oid}/decision",
        {
            "revision": lot["revision"],
            "accept": True,
            "note": "허용 여부 확인했음",
            "scope_checked": True,
            "intake_checked": True,
        },
    )
    assert r.status_code == 409
