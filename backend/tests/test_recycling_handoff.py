from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.domains.diagnosis.recycling import recycling_for_handoff
from app.domains.diagnosis.schemas import TreatmentSelectionIn
from app.domains.diagnosis.treatment import context_from_handoff
from app.domains.transport.workflow import process_request
from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.reference import PlanningReference, read_bundle
from tests.test_diagnosis_treatment import COMPANY, detail


def with_recycling():
    d = detail()
    d["handoff"]["timestamps"] = {"as_of": "2026-11-16"}
    d["recycling"] = {
        "contract": "recycling-types-v1",
        "case_id": "C1",
        "verdict_version": 1,
        "waste_code": "51-03-01",
        "as_of": "2026-11-16",
        "status": "table_listed",
        "types": {"free": ["R-3-3", "R-10"], "analysis": ["R-8-1", "R-10"], "unmarked": []},
        "version": "test-annex43",
        "checksum": "a" * 64,
        "source": {"url": "https://www.law.go.kr/test", "law_effective_from": "2026-11-12"},
        "pages": [9],
        "notes": ["표의 범위이며 업체 허가는 미확인"],
        "facility_permit_verified": False,
    }
    return d


def test_legacy_supplement_and_new_handoff_preserve_groups_for_every_candidate():
    d = with_recycling()
    original = deepcopy(d["handoff"])
    ctx = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="scrap"), COMPANY)
    assert ctx.recycling == d["recycling"] and d["handoff"] == original
    packets = build_intake_batch(
        IntakeSelection.model_validate(
            {k: v for k, v in ctx.route_input.items() if k not in {"origin", "preview_transition"}}
        ),
        PlanningReference.model_validate(read_bundle("planning-reference.json")),
    )
    assert len(packets) > 5
    for packet in packets:
        assert packet["recycling_types"] == d["recycling"]["types"]
        assert packet["recycling_basis"]["source_url"].startswith("https://www.law.go.kr/")
        assert "case_id" not in packet["recycling_basis"]
    d["handoff"]["recycling"] = d.pop("recycling")
    assert recycling_for_handoff(d)["types"]["analysis"] == ["R-8-1", "R-10"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("case_id", "other"),
        ("verdict_version", 2),
        ("waste_code", "51-29-01"),
        ("as_of", "2026-11-15"),
        ("facility_permit_verified", True),
    ],
)
def test_mismatched_engine_supplement_is_not_sent(key, value):
    d = with_recycling()
    d["recycling"][key] = value
    assert recycling_for_handoff(d) is None
    ctx = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form="scrap"), COMPANY)
    assert ctx.route_input["recycling_types"] is None


def test_b_output_never_reuses_a_recycling_types():
    d = with_recycling()
    lot = SimpleNamespace(
        data={
            "initial": {"waste_code": "51-03-01", "material": "pp", "input_form": "scrap"},
            "recycling": d["recycling"],
            "completed": [],
            "current": {},
        }
    )
    assert process_request(lot).recycling_types.analysis == ["R-8-1", "R-10"]
    lot.data["completed"] = [{"transition_key": "pp-sorting"}]
    lot.data["current"] = {"state_key": "pp-sorted", "mass_kg": 90}
    request = process_request(lot)
    assert request.recycling_types is None and request.recycling_basis is None
