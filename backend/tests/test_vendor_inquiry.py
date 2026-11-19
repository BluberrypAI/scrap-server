"""Synthetic companies. Inquiry preparation is not an offer or certification."""

import uuid
from copy import deepcopy

import pytest

from app.domains.companies.models import Company
from app.domains.transport.models import WorkflowLot
from tests.test_pp_company_workflow import accept_receive, choose, save_output
from tests.test_pp_company_workflow import setup_flow as _setup_flow

setup_flow = _setup_flow


async def reviewed(req, lot, role="A"):
    response = await req(role, f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def selection(lot, unregistered=False):
    fs = [f for o in lot["review"]["next_step"]["options"] for f in o["facilities"]]
    f = next(f for f in fs if not f["recipient"]) if unregistered else fs[0]
    return {"revision": lot["revision"], "capability_key": f["capability_key"]}


async def test_unregistered_vendor_packet_is_private_and_does_not_change_lot(setup_flow):
    req, create, _, _ = setup_flow
    lot = await reviewed(req, await create())
    response = await req("A", f"/lots/{lot['id']}/inquiry-packet", selection(lot, True))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    text = response.json()["text"]
    assert "1000 kg" in text and "추가 근거 필요" in text and "미확인" in text
    assert "반입조건과 일정을 메시지로" in text and "확인일:" in text
    assert "미응답" not in text and "시험성적서는 별도로" not in text
    assert "필요한 샘플·검사 항목" not in text
    assert "@example.com" not in text and "/photos/" not in text and "?t=" not in text
    assert lot["id"] not in text and lot["current_company_id"] not in text
    after = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    assert after["revision"] == lot["revision"] and after["offers"] == []
    assert after["data"] == lot["data"] and after["status"] == lot["status"]


async def test_packet_denies_third_party_wrong_candidate_and_stale_revision(setup_flow):
    req, create, _, _ = setup_flow
    lot = await reviewed(req, await create())
    path = f"/lots/{lot['id']}/inquiry-packet"
    body = selection(lot)
    assert (await req("D", path, body)).status_code == 404
    assert (
        await req("A", path, {**body, "capability_key": "not-in-current-candidates"})
    ).status_code == 409
    assert (await req("A", path, {**body, "revision": lot["revision"] + 1})).status_code == 409


@pytest.mark.parametrize("endpoint", ["inquiry-packet", "offers"])
async def test_changed_site_blocks_old_packet_and_offer(setup_flow, db, endpoint):
    req, create, actors, _ = setup_flow
    lot = await reviewed(req, await create())
    company = await db.get(Company, uuid.UUID(actors["A"][1]))
    company.site_address = "변경한 시험 사업장"
    company.profile_version += 1
    await db.commit()
    response = await req("A", f"/lots/{lot['id']}/{endpoint}", selection(lot))
    assert response.status_code == 409
    assert "사업장 정보" in response.json()["message"]
    updated = await reviewed(req, lot)
    if endpoint == "inquiry-packet":
        result = await req("A", f"/lots/{lot['id']}/{endpoint}", selection(updated))
        assert result.status_code == 200
        assert "변경한 시험 사업장" in result.json()["text"]


@pytest.mark.parametrize(
    "status,finding,expected",
    [
        ("model_unavailable", None, "AI 검토 미완료"),
        ("reviewed", "restriction_mentioned", "반입 제한 근거"),
    ],
)
async def test_failed_or_restricted_review_remains_visible_in_packet(
    setup_flow, db, status, finding, expected
):
    req, create, _, _ = setup_flow
    lot = await reviewed(req, await create())
    body = selection(lot)
    stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    review = deepcopy(stored.review)
    review["results"][body["capability_key"]]["status"] = status
    review["results"][body["capability_key"]]["finding"] = finding
    stored.review = review
    await db.commit()
    response = await req("A", f"/lots/{lot['id']}/inquiry-packet", body)
    assert response.status_code == 200
    assert expected in response.json()["text"]
    assert (await req("A", f"/lots/{lot['id']}/offers", body)).status_code == 409


async def test_b_packet_uses_observed_output_not_a_initial_form(setup_flow):
    req, create, _, _ = setup_flow
    lot = await choose(req, await create(), "A", "sarom-hwaseong-2")
    lot = await accept_receive(req, lot, "A", "B")
    lot = await save_output(req, lot, "B", "pp-shredded", 950)
    lot = await reviewed(req, lot, "B")
    body = selection(lot)
    path = f"/lots/{lot['id']}/inquiry-packet"
    assert (await req("A", path, body)).status_code == 403
    result = await req("B", path, body)
    assert result.status_code == 200, result.text
    text = result.json()["text"]
    assert "950 kg" in text and "1000 kg" not in text
    assert "발송 기업: B" in text and "최초 배출 시 분류번호" in text
    assert "최초 분류번호·R유형을 이번 인계에 자동 적용하지 않습니다" in text
