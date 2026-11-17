from sqlalchemy import select

from app.domains.transport.models import SupplierIntakePolicy
from tests.test_pp_company_workflow import accept_receive, choose, save_output
from tests.test_pp_company_workflow import setup_flow as _setup_flow
from tests.test_vendor_inquiry import reviewed

setup_flow = _setup_flow
FACILITY = "sarom-hwaseong-2"
POLICY = dict(
    accepting_inquiries=True,
    materials_forms="시험 PP 사출 잔재",
    contamination="수분 자료 확인",
    packaging="시험 마대 포장",
    schedule="입고 전 일정 협의",
    min_mass_kg=100,
    max_mass_kg=2000,
    required_checks=["수분 확인 자료를 제출해 주세요"],
)


async def save(req, role="B", version=0, **changes):
    return await req(
        role,
        "/supplier-policies",
        {
            "facility_key": FACILITY,
            "expected_version": version,
            "policy": {**POLICY, **changes},
        },
    )


async def test_only_bound_company_can_write_and_versions_are_immutable(setup_flow, db):
    req, _, _, _ = setup_flow
    assert (await save(req, "A")).status_code == 403
    assert (await save(req, min_mass_kg=3000)).status_code == 422
    assert (await save(req, required_checks=[" "])).status_code == 422
    first = await save(req)
    assert first.status_code == 200, first.text
    assert first.json()["basis"] == "supplier_declared_not_certified"
    assert (await save(req)).status_code == 409
    second = await save(req, version=1, packaging="수정한 시험 포장")
    assert second.status_code == 200
    rows = (
        await db.scalars(select(SupplierIntakePolicy).order_by(SupplierIntakePolicy.version))
    ).all()
    assert len(rows) == 2 and rows[0].data["packaging"] == "시험 마대 포장"
    sites = (await req("B", "/supplier-policies", method="GET")).json()
    assert sites[0]["current"]["version"] == 2
    assert (await req("A", "/supplier-policies", method="GET")).json() == []


def pick(lot):
    return next(
        f
        for o in lot["review"]["next_step"]["options"]
        for f in o["facilities"]
        if f["facility_key"] == FACILITY
    )


async def test_policy_change_invalidates_review_and_pause_blocks_new_inquiry(setup_flow):
    req, create, _, _ = setup_flow
    lot = await reviewed(req, await create())
    candidate = pick(lot)
    assert (await save(req, accepting_inquiries=False)).status_code == 200
    body = {"revision": lot["revision"], "capability_key": candidate["capability_key"]}
    assert (await req("A", f"/lots/{lot['id']}/offers", body)).status_code == 409
    lot = await reviewed(req, lot)
    assert pick(lot)["supplier_policy"]["policy"]["accepting_inquiries"] is False
    body["revision"] = lot["revision"]
    assert (await req("A", f"/lots/{lot['id']}/offers", body)).status_code == 409


async def test_inquiry_conditional_acceptance_and_qr_with_frozen_policy(setup_flow):
    req, create, _, _ = setup_flow
    assert (await save(req)).status_code == 200
    lot = await reviewed(req, await create())
    response = await req(
        "A",
        f"/lots/{lot['id']}/offers",
        {"revision": lot["revision"], "capability_key": pick(lot)["capability_key"]},
    )
    assert response.status_code == 200, response.text
    lot = response.json()
    oid = lot["offers"][-1]["id"]
    for role in ["B", "A"]:
        r = await req(
            role,
            f"/offers/{oid}/messages",
            {"revision": lot["revision"], "text": f"{role} 시험 문의 답변"},
        )
        assert r.status_code == 200, r.text
        lot = r.json()
    assert len(lot["offers"][-1]["data"]["messages"]) == 2
    assert (
        await req(
            "D", f"/offers/{oid}/messages", {"revision": lot["revision"], "text": "다른 기업 접근"}
        )
    ).status_code in {403, 404}
    assert (
        await req(
            "A", f"/offers/{oid}/messages", {"revision": lot["revision"] - 1, "text": "오래된 화면"}
        )
    ).status_code == 409
    assert (
        await req("A", f"/offers/{oid}/messages", {"revision": lot["revision"], "text": " "})
    ).status_code == 422
    decision = {
        "accept": True,
        "note": "합성 자료 확인",
        "scope_checked": True,
        "intake_checked": True,
    }
    assert (
        await req("B", f"/offers/{oid}/decision", {"revision": lot["revision"], **decision})
    ).status_code == 409
    assert (await req("A", f"/offers/{oid}/qr", {"revision": lot["revision"]})).status_code == 403
    # Later edits apply to new inquiries, not the already-shared snapshot.
    assert (await save(req, version=1, required_checks=["변경한 다른 자료"])).status_code == 200
    r = await req(
        "B",
        f"/offers/{oid}/conditions",
        {"revision": lot["revision"], "conditions": ["시험 포장 확인"], "note": "합성 조건부 수락"},
    )
    assert r.status_code == 200, r.text
    lot = r.json()
    offer = lot["offers"][-1]
    assert offer["data"]["facility"]["supplier_policy"]["version"] == 1
    checks = offer["data"]["conditions"]
    assert {c["text"] for c in checks} == {POLICY["required_checks"][0], "시험 포장 확인"}
    assert (
        await req(
            "B",
            f"/offers/{oid}/decision",
            {
                "revision": lot["revision"],
                **decision,
                "resolved_condition_ids": [c["id"] for c in checks],
            },
        )
    ).status_code == 409
    r = await req(
        "A",
        f"/offers/{oid}/condition-responses",
        {"revision": lot["revision"], "responses": {c["id"]: "TEST-001 합성 증빙" for c in checks}},
    )
    assert r.status_code == 200, r.text
    lot = r.json()
    r = await req(
        "B",
        f"/offers/{oid}/decision",
        {
            "revision": lot["revision"],
            **decision,
            "resolved_condition_ids": [c["id"] for c in checks],
        },
    )
    assert r.status_code == 200, r.text
    lot = r.json()
    assert (
        await req(
            "A", f"/offers/{oid}/messages", {"revision": lot["revision"], "text": "수락 후 변경"}
        )
    ).status_code == 409
    qr = (await req("A", f"/offers/{oid}/qr", {"revision": lot["revision"]})).json()
    r = await req("B", f"/offers/{oid}/receive", {"revision": qr["revision"], "token": qr["token"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "processing"


async def test_previous_holder_cannot_answer_b_to_c_inquiry(setup_flow):
    req, create, _, _ = setup_flow
    lot = await choose(req, await create(), "A", FACILITY)
    lot = await accept_receive(req, lot, "A", "B")
    lot = await save_output(req, lot, "B", "pp-shredded", 950)
    lot = await choose(req, lot, "B", "veolia-doksan-hwaseong")
    oid = lot["offers"][-1]["id"]
    assert (
        await req(
            "A",
            f"/offers/{oid}/messages",
            {"revision": lot["revision"], "text": "이전 배출자가 대신 답변"},
        )
    ).status_code == 403
    for role in ["B", "C"]:
        response = await req(
            role,
            f"/offers/{oid}/messages",
            {"revision": lot["revision"], "text": "후속 인계 시험 문의"},
        )
        assert response.status_code == 200, response.text
        lot = response.json()
    assert len(lot["offers"][-1]["data"]["messages"]) == 2
