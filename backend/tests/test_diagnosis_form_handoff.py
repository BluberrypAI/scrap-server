from copy import deepcopy

import httpx
import pytest

from app.domains.diagnosis.schemas import TreatmentSelectionIn
from app.domains.diagnosis.treatment import context_from_handoff
from app.domains.treatment.repository import replace_snapshots
from tests.test_diagnosis_treatment import COMPANY, detail
from tests.test_diagnosis_treatment import fake_engine as _fake_engine

fake_engine = _fake_engine


def response(text, material="pp", code="51-03-01"):
    d = detail()
    d["handoff"]["facts"]["material"]["value"] = material
    d["handoff"]["waste_code"] = code
    d["conversation"] = [{"role": "user", "text": text, "turn_id": "T1"}]
    return d


@pytest.mark.parametrize(
    "text,material,code,expected",
    [
        ("PP 사출 잔재입니다", "pp", "51-03-01", "scrap"),
        ("PP 파쇄품이고 순도는 모릅니다", "pp", "51-03-01", "shredded"),
        ("PP 파쇄품 100kg을 내일 업체에 보낼 예정입니다", "pp", "51-03-01", "shredded"),
        ("PE 폐비닐 필름입니다", "pe", "51-03-01", "film"),
        ("PE 필름 압축 베일입니다", "pe", "51-03-07", "film-bale"),
        ("PET 파쇄품입니다", "pet", "51-03-01", "flake"),
        ("PET병입니다", "pet", "51-03-07", "bottle"),
        ("알루미늄 스크랩입니다", "aluminium", "51-29-02", "scrap"),
        ("알루미늄 음료캔입니다", "aluminium", "51-29-03", "can"),
        ("폐철드럼입니다", "ferrous_scrap", "51-29-04", "drum"),
        ("PA6 폐어망입니다", "pa6", "51-03-08", "net"),
        ("EPS 스티로폼 부표입니다", "eps", "51-03-05", "buoy"),
    ],
)
def test_explicit_form_from_existing_conversation_preserves_code_and_material(
    text, material, code, expected
):
    d = response(text, material, code)
    before = deepcopy(d)
    result = context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY)
    assert result.status == "ready"
    assert result.selected_form == result.route_input["input_form"] == expected
    assert result.route_input["waste_code"] == code
    assert result.route_input["material"] == (
        "ferrous" if material == "ferrous_scrap" else material
    )
    assert result.form_source == "conversation" and result.form_turn_id == "T1"
    assert result.form_quote == text
    assert d == before


@pytest.mark.parametrize(
    "text",
    [
        "PP 고체입니다",
        "PP 사출 공정에서 발생했습니다",
        "파쇄할 예정입니다",
        "PP 파쇄품으로 만들 계획입니다",
        "PP 파쇄품은 아닙니다",
        "파쇄품인지 모르겠어요",
        "아마 PP 파쇄품 같아요",
        "예를 들어 PP 파쇄품이면 가능한가요?",
        "PP 사출잔재와 파쇄품이 섞여 있습니다",
        "예전에는 PP 파쇄품이었습니다",
        "PP 파쇄품이면 되는 건가요",
        "PP 파쇄품은 어떻게 처리하나요",
        "not PP flakes",
        "will produce PP pellets",
        "maybe PP scraps",
    ],
)
def test_missing_uncertain_negative_future_and_mixed_forms_still_require_selection(text):
    result = context_from_handoff(response(text), "C1", TreatmentSelectionIn(), COMPANY)
    assert result.status == "needs_input" and result.selected_form is None
    assert result.route_input is None


@pytest.mark.parametrize(
    "change", [{"role": "assistant"}, {"document_id": "D1"}, {"quick_reply": {"key": "x"}}]
)
def test_non_statement_conversation_entries_are_not_form_evidence(change):
    d = response("PP 파쇄품입니다")
    d["conversation"][0].update(change)
    assert context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY).selected_form is None


def test_conflicting_or_withdrawn_form_does_not_silently_choose_last_mention():
    for text in ["PP 사출 잔재입니다", "현재 형태는 모르겠습니다"]:
        d = response("PP 파쇄품입니다")
        d["conversation"].append({"role": "user", "text": text, "turn_id": "T2"})
        assert context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY).selected_form is None


def test_reopened_case_does_not_reuse_old_form_but_accepts_new_statement():
    d = response("PP 사출 잔재입니다")
    d["conversation"][0]["at"] = "2026-11-19T10:00:00+09:00"
    d["verdicts"] = [{"reopened_at": "2026-11-19T11:00:00+09:00"}]
    assert context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY).selected_form is None
    d["conversation"].append(
        {
            "role": "user",
            "text": "PP 파쇄품입니다",
            "turn_id": "T2",
            "at": "2026-11-19T11:01:00+09:00",
        }
    )
    assert (
        context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY).selected_form == "shredded"
    )


def test_structured_known_form_takes_precedence_and_unknown_does_not_fall_back():
    d = response("PP 사출 잔재입니다")
    d["handoff"]["facts"]["input_form"] = {"value": "파쇄품", "status": "CLAIMED"}
    result = context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY)
    assert result.selected_form == "shredded" and result.form_source == "handoff"
    d["handoff"]["facts"]["input_form"]["status"] = "DECLARED_UNKNOWN"
    assert context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY).selected_form is None


def test_manual_correction_and_unsupported_observation_are_not_silently_rewritten():
    d = response("PP 사출 잔재입니다")
    result = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="shredded"), COMPANY)
    assert result.selected_form == "shredded" and result.form_source == "user_input"
    assert result.form_quote is None and d["handoff"]["facts"]["material"]["value"] == "pp"
    unsupported = context_from_handoff(
        response("PP 스티로폼입니다"), "C1", TreatmentSelectionIn(), COMPANY
    )
    assert unsupported.status == "unsupported" and unsupported.selected_form == "foam"


async def test_next_step_without_form_then_lot_registration_keeps_statement_source(
    company_client, fake_engine, db
):
    await replace_snapshots(db)
    fake_engine.reply = httpx.Response(200, json=response("PP 파쇄품입니다"))
    result = await company_client.post("/api/v1/diagnosis/cases/C1/treatment/next-step", json={})
    assert result.status_code == 200
    context = result.json()
    assert context["status"] == "ready" and context["route_input"]["material"] == "pp"
    assert context["selected_form"] == "shredded" and context["form_source"] == "conversation"
    created = await company_client.post(
        "/api/v1/workflow/lots",
        json={
            "diagnosis_id": "C1",
            "input_form": context["selected_form"],
            "mass_kg": 100,
            "condition": "합성 PP 시험 물량",
        },
    )
    assert created.status_code == 200, created.text
    lot = created.json()
    assert lot["data"]["initial"]["input_form"] == "shredded"
    assert lot["data"]["initial"]["material"] == "pp"
    assert lot["data"]["sender_confirmations"]["input_form_source"] == "conversation"
    assert lot["data"]["sender_confirmations"]["input_form_turn_id"] == "T1"
