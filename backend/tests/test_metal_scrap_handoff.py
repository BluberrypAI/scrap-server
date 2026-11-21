"""문진 v2 금속 스크랩 인계(D18): 철은 steel, 알루미늄은 aluminium으로 온다."""

import pytest

from app.domains.diagnosis.schemas import TreatmentSelectionIn
from app.domains.diagnosis.treatment import context_from_handoff
from app.domains.treatment.reference import resolve_material
from tests.test_diagnosis_treatment import COMPANY, detail


def v2_detail(material, form, code):
    d = detail()
    d["handoff"]["waste_code"] = code
    d["handoff"]["facts"] = {
        "material": {"value": material, "status": "CLAIMED"},
        "input_form": {"value": form, "status": "CLAIMED"},
        "physical_state": {"value": "solid", "status": "DERIVED"},
    }
    d["handoff"]["assumptions"] = [
        "고철·알루미늄 스크랩은 지정 순환자원 준수사항을 마치고 순환자원정보센터에 등록하면 "
        "폐기물로 보지 않아요. 등록하지 않은 것으로 보고 폐기물로 판정했어요."
    ]
    return d


def test_engine_steel_name_resolves_to_ferrous():
    assert resolve_material("steel") == "ferrous"
    assert resolve_material("철") == "ferrous"


@pytest.mark.parametrize(
    ("material", "code", "route_material"),
    [("aluminium", "51-29-02", "aluminium"), ("steel", "51-29-01", "ferrous")],
)
def test_v2_metal_scrap_handoff_is_ready_with_original_code(material, code, route_material):
    result = context_from_handoff(
        v2_detail(material, "scrap", code), "C1", TreatmentSelectionIn(), COMPANY
    )
    assert result.status == "ready"
    assert result.form_source == "handoff" and result.selected_form == "scrap"
    assert result.route_input["waste_code"] == code
    assert result.route_input["material"] == route_material
    assert result.route_input["input_form"] == "scrap"
    assert any("순환자원" in w for w in result.warnings)


def test_v2_steel_can_stays_unsupported():
    # 철캔(51-29-03)은 엔진이 route_unsupported로 내고, 서버 철 공정에도 51-29-03이 없다
    result = context_from_handoff(
        v2_detail("steel", "can", "51-29-03"), "C1", TreatmentSelectionIn(), COMPANY
    )
    assert result.status == "unsupported" and result.route_input is None
