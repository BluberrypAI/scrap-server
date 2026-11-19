from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from app.domains.diagnosis.client import get_engine_client
from app.domains.diagnosis.schemas import TreatmentSelectionIn
from app.domains.diagnosis.treatment import context_from_handoff
from app.domains.treatment.material_scope import FORM_CODES
from app.domains.treatment.repository import replace_snapshots
from app.main import app
from tests.test_diagnosis import FakeEngine


@pytest.fixture
def fake_engine():
    fake = FakeEngine()
    app.dependency_overrides[get_engine_client] = fake.client
    yield fake
    app.dependency_overrides.pop(get_engine_client, None)


HANDOFF = {
    "contract": "diagnosis-handoff-v1",
    "case_id": "C1",
    "verdict_version": 1,
    "result_type": "WASTE_CODE",
    "waste_code": "51-03-01",
    "category": "GENERAL",
    "route_guidance": {"action": "RECOMMEND_ROUTE"},
    "review": "UNVERIFIED",
    "facts": {"material": {"value": "pp"}, "physical_state": {"value": "solid"}},
    "assumptions": ["일부 항목은 진술로 확인했습니다."],
}
COMPANY = SimpleNamespace(
    site_address="가상 화성 사업장", site_latitude=37.16, site_longitude=126.90
)
BASE = "/api/v1/diagnosis/cases/C1/treatment"


def detail():
    return {"case": {"id": "C1", "status": "CODE_CONFIRMED"}, "handoff": deepcopy(HANDOFF)}


def test_missing_can_state_requires_explicit_confirmation_and_preserves_handoff():
    d = detail()
    d["handoff"]["waste_code"] = "51-29-03"
    d["handoff"]["facts"] = {"material": {"value": "metal_can"}}
    waiting = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="can"), COMPANY)
    assert waiting.status == "needs_input" and waiting.requires_solid_confirmation
    confirmed = context_from_handoff(
        d, "C1", TreatmentSelectionIn(input_form="can", solid_confirmed=True), COMPANY
    )
    assert confirmed.status == "ready"
    assert confirmed.route_input["material"] == "aluminium"
    assert "physical_state" not in confirmed.handoff["facts"]
    d["handoff"]["facts"]["physical_state"] = {"value": "liquid"}
    conflict = context_from_handoff(
        d, "C1", TreatmentSelectionIn(input_form="can", solid_confirmed=True), COMPANY
    )
    assert conflict.status == "review_required" and conflict.route_input is None


def test_form_is_not_invented_and_warnings_survive():
    result = context_from_handoff(detail(), "C1", TreatmentSelectionIn(), COMPANY)
    assert result.status == "needs_input"
    assert {x["value"] for x in result.available_forms} == {
        "scrap",
        "rigid",
        "film",
        "bale",
        "shredded",
        "flake",
        "pellet",
    }
    assert result.handoff["review"] == "UNVERIFIED"
    assert any("R코드" in x for x in result.warnings)
    assert result.route_input is None


def test_real_ferrous_classifier_name_bridges_but_generic_nonferrous_does_not():
    d = detail()
    d["handoff"]["facts"]["material"]["value"] = "ferrous_scrap"
    d["handoff"]["waste_code"] = "51-29-01"
    context = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="scrap"), COMPANY)
    assert context.status == "ready" and context.route_input["material"] == "ferrous"
    d["handoff"]["facts"]["material"]["value"] = "nonferrous_scrap"
    d["handoff"]["waste_code"] = "51-29-02"
    assert (
        context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="scrap"), COMPANY).status
        == "needs_input"
    )


PLASTIC_HANDOFFS = [
    (material, form, code)
    for (material, form), codes in FORM_CODES.items()
    if material != "aluminium"
    for code in codes
]


@pytest.mark.parametrize("material,form,code", PLASTIC_HANDOFFS)
async def test_plastic_handoff_preserves_code_and_queries_actual_reference(
    company_client, fake_engine, db, material, form, code
):
    """지원 조합의 번호를 보존한다. 빈 후보를 다른 번호로 우회하지 않는다."""
    await replace_snapshots(db)
    d = detail()
    d["handoff"]["waste_code"] = code
    d["handoff"]["facts"]["material"]["value"] = material
    fake_engine.reply = httpx.Response(200, json=d)
    waiting = await company_client.post(BASE + "/next-step", json={})
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "needs_input"
    assert form in {item["value"] for item in waiting.json()["available_forms"]}
    result = await company_client.post(BASE + "/next-step", json={"input_form": form})
    assert result.status_code == 200
    context = result.json()
    assert context["status"] == "ready"
    assert context["route_input"]["waste_code"] == context["handoff"]["waste_code"] == code
    assert context["route_input"]["material"] == material
    assert context["route_input"]["recycling_types"] is None
    next_step = context["next_step"]
    assert next_step["current_state"]
    held = material == "ps" and form == "bale"
    expected_status = "no_route" if held else "candidates"
    assert next_step["status"] == expected_status
    assert bool([f for p in next_step["options"] for f in p["facilities"]]) == (
        expected_status == "candidates"
    )
    assert next_step["message"]
    assert next_step["dispatch_approved"] is False


@pytest.mark.parametrize("material", ["pet", "PET", "페트"])
def test_pet_ordinary_resin_handoff_offers_forms_without_changing_code(material):
    d = detail()
    d["handoff"]["facts"]["material"]["value"] = material
    context = context_from_handoff(d, "C1", TreatmentSelectionIn(), COMPANY)
    assert context.status == "needs_input"
    assert {x["value"] for x in context.available_forms} == {"bottle", "bale", "flake"}
    assert context.handoff["waste_code"] == "51-03-01"


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"result_type": "NO_CODE", "waste_code": None}, "review_required"),
        ({"category": "DESIGNATED"}, "review_required"),
        ({"waste_code": "51-29-01"}, "unsupported"),
        (
            {"facts": {"material": {"value": "pp"}, "physical_state": {"value": "liquid"}}},
            "review_required",
        ),
        ({"route_guidance": {"action": "NEEDS_TEST"}}, "review_required"),
    ],
)
def test_no_generic_route_for_ineligible_handoffs(change, expected):
    d = detail()
    d["handoff"].update(change)
    result = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="scrap"), COMPANY)
    assert result.status == expected
    assert result.route_input is None


async def test_confirmed_pp_routes_and_ai_cover_every_candidate(
    company_client, fake_engine, db, monkeypatch
):
    await replace_snapshots(db)
    fake_engine.reply = httpx.Response(200, json=detail())
    scrap = (await company_client.post(BASE + "/next-step", json={"input_form": "scrap"})).json()
    shredded = (
        await company_client.post(BASE + "/next-step", json={"input_form": "shredded"})
    ).json()
    assert scrap["next_step"]["status"] == shredded["next_step"]["status"] == "candidates"
    assert {x["transition_key"] for x in scrap["next_step"]["options"]} != {
        x["transition_key"] for x in shredded["next_step"]["options"]
    }
    assert scrap["route_input"]["recycling_types"] is None
    assert scrap["origin"] is None  # no invented Huaseong coordinate from an address
    expected = {f["capability_key"] for p in scrap["next_step"]["options"] for f in p["facilities"]}
    seen = []
    from app.domains.treatment.intake import IntakeBatchResult, IntakeResult

    async def review(packets, settings):
        seen.extend(packets)
        return IntakeBatchResult(
            results={
                p["capability_key"]: IntakeResult(status="needs_evidence", next_check="추가 확인")
                for p in packets
            }
        )

    monkeypatch.setattr("app.domains.diagnosis.treatment.review_intakes", review)
    audited = (
        await company_client.post(BASE + "/intake-reviews", json={"input_form": "scrap"})
    ).json()
    assert expected == set(audited["reviews"]["results"]) == {p["capability_key"] for p in seen}
    assert all("origin" not in p and "case_id" not in p and not p["recycling_types"] for p in seen)
    assert all(not r["dispatch_approved"] for r in audited["reviews"]["results"].values())
    assert fake_engine.last.headers["X-Company-Id"]


@pytest.mark.parametrize(
    "extra",
    ["waste_code", "material", "recycling_types", "origin", "company_id", "completed_transitions"],
)
async def test_browser_cannot_inject_verdict_or_progress(company_client, fake_engine, extra):
    response = await company_client.post(BASE + "/next-step", json={extra: "forged"})
    assert response.status_code == 422
    assert not fake_engine.requests


async def test_reopen_does_not_reuse_old_verdict(company_client, fake_engine):
    d = detail()
    d["case"]["status"] = "DIAGNOSING"
    d["handoff"] = None
    d["verdicts"] = [{"handoff": HANDOFF}]
    fake_engine.reply = httpx.Response(200, json=d)
    result = (await company_client.post(BASE + "/next-step", json={"input_form": "scrap"})).json()
    assert result["status"] == "review_required"
    assert result["next_step"] is None


async def test_case_isolation_and_login(client, company_client, fake_engine, other_client):
    fake_engine.reply = httpx.Response(
        404, json={"detail": {"code": "CASE_NOT_FOUND", "message": "다른 기업 건"}}
    )
    res = await other_client.post(BASE + "/next-step", json={})
    assert res.status_code == 404
    client.cookies.clear()
    res = await client.post(BASE + "/next-step", json={})
    assert res.status_code == 401


async def test_reopen_during_model_call_invalidates_result(
    company_client, fake_engine, db, monkeypatch
):
    from app.domains.treatment.intake import IntakeBatchResult

    await replace_snapshots(db)
    fake_engine.reply = httpx.Response(200, json=detail())

    async def review(packets, settings):
        fake_engine.reply = httpx.Response(
            200, json={"case": {"status": "DIAGNOSING"}, "handoff": None}
        )
        return IntakeBatchResult(results={})

    monkeypatch.setattr("app.domains.diagnosis.treatment.review_intakes", review)
    response = await company_client.post(BASE + "/intake-reviews", json={"input_form": "scrap"})
    assert response.status_code == 200
    assert response.json()["status"] == "review_required"
    assert response.json()["next_step"] is None
    assert response.json()["reviews"] is None
