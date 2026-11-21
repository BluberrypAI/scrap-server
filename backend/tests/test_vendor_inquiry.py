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


@pytest.mark.parametrize("distance", [None, 24.5, 0.0])
async def test_mail_body_includes_only_vendor_facing_details(setup_flow, db, distance):
    req, create, actors, _ = setup_flow
    company = await db.get(Company, uuid.UUID(actors["A"][1]))
    company.site_address = "경기도 시흥시 산단로 123-4 (정왕동)"
    lot = await reviewed(req, await create())
    body = selection(lot, unregistered=True)
    stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    review = deepcopy(stored.review)
    option = next(
        option
        for option in review["next_step"]["options"]
        if any(f["capability_key"] == body["capability_key"] for f in option["facilities"])
    )
    facility = next(
        f for f in option["facilities"] if f["capability_key"] == body["capability_key"]
    )
    if distance is not None:
        facility.update(road_distance_status="available", road_distance_km=distance)
    stored.review = review
    await db.commit()

    response = await req("A", f"/lots/{lot['id']}/inquiry-packet", body)
    assert response.status_code == 200, response.text
    packet = response.json()
    mail = packet["mail_body"]
    assert packet["version"] == "vendor-inquiry-v1"
    assert len(mail) <= 900 and "\r" not in mail
    for forbidden in ("AI", "UTC", "http", "123-4", "정왕동", lot["id"], body["capability_key"]):
        assert forbidden not in mail
    assert mail.startswith(f"안녕하세요, {facility['label']} 담당자님.\nA 시흥 1공장입니다.")
    assert "\n- 품목: PP " in mail and "\n- 중량: 1000 kg" in mail
    assert "\n- 상태: 합성 테스트 PP" in mail
    assert f"\n- 폐기물 분류번호(참고): {lot['data']['initial']['waste_code']}" in mail
    process = f"{option['input_state']['label']} → {option['output_state']['label']}"
    origin_line = "- 출발지: 경기도 시흥시"
    if distance is not None:
        origin_line += f" (도로 약 {distance:.1f} km)"
    assert f"\n{origin_line}\n- 희망 처리: {process}\n" in mail
    assert "\n3. 처리 단가와 가능한 일정\n" in mail
    assert mail.endswith("A 드림 (manager@example.com)")
    assert "manager@example.com" not in packet["text"]


async def test_mail_body_caps_long_condition_and_keeps_full_reply_address(setup_flow, db):
    req, create, actors, _ = setup_flow
    company = await db.get(Company, uuid.UUID(actors["A"][1]))
    company.company_name = "가" * 200
    company.site_name = "나" * 200
    email = "m" * 308 + "@example.com"
    company.contact_email = email
    lot = await reviewed(req, await create())
    body = selection(lot)
    stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    condition = f"AI 검토\r\nUTC https://example.com {lot['id']} " + "다" * 1300
    stored.data = {**stored.data, "current": {**stored.data["current"], "condition": condition}}
    await db.commit()

    response = await req("A", f"/lots/{lot['id']}/inquiry-packet", body)
    assert response.status_code == 200, response.text
    packet = response.json()
    mail = packet["mail_body"]
    assert len(mail) == 900
    assert f"드림 ({email})" in mail and "처리 단가와 가능한 일정" in mail
    assert "\n- 상태: 검토 다" in mail and "다…\n" in mail
    assert all(value not in mail for value in ("AI", "UTC", "http", "\r", lot["id"]))
    assert condition in packet["text"]


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
    mail = result.json()["mail_body"]
    assert "950 kg" in mail and "1000 kg" not in mail
    assert "폐기물 분류번호" not in mail


def test_origin_region_accepts_address_starting_with_district():
    from app.domains.transport.inquiry import _origin_region

    assert _origin_region("과천시") == "과천시"
    assert _origin_region("경기도 화성시 남양읍 시청로 159 (시험용)") == "경기도 화성시"
    assert _origin_region("주소 미상") is None


def test_summary_item_does_not_repeat_material_prefix():
    from app.domains.transport.inquiry import _inquiry_summary

    lot = type("Lot", (), {"data": {"current": {"mass_kg": 10}, "completed": [], "initial": {}}})()
    company = type("Company", (), {"site_address": "과천시"})()
    option = {"input_state": {"label": "A"}, "output_state": {"label": "B"}}
    summary = _inquiry_summary(lot, company, option, {}, "PE", "PE 잔재·로트 규격 미확인")
    assert summary.item == "PE 잔재·로트 규격 미확인"
    summary = _inquiry_summary(lot, company, option, {}, "알루미늄", "사용 후 알루미늄 음료캔")
    assert summary.item == "사용 후 알루미늄 음료캔"
    summary = _inquiry_summary(lot, company, option, {}, "PP", "파쇄품")
    assert summary.item == "PP 파쇄품"
