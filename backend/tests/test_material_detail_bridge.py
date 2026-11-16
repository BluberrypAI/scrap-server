"""A submaterial confirmation must narrow, never replace, the diagnosis."""

from copy import deepcopy

import httpx
import pytest

from app.domains.diagnosis.schemas import TreatmentSelectionIn
from app.domains.diagnosis.treatment import context_from_handoff
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.repository import replace_snapshots
from app.domains.treatment.schemas import NextStepRequest
from tests.test_diagnosis_treatment import COMPANY, detail, fake_engine  # noqa: F401

CASES = [
    ("plastic_packaging", "51-03-07", "pp", "scrap"),
    ("plastic_packaging", "51-03-07", "pe", "film"),
    ("plastic_packaging", "51-03-07", "pet", "bottle"),
    ("fishing_net", "51-03-08", "pa6", "net"),
    ("other_resin", "51-03-01", "san", "rigid"),
    ("other_resin", "51-03-01", "pa66", "shredded"),
    ("other_resin", "51-03-01", "pcabs", "shredded"),
    ("nonferrous_scrap", "51-29-02", "aluminium", "scrap"),
    ("aqua_buoy", "51-03-05", "eps", "buoy"),
    ("metal_container", "51-29-04", "ferrous", "drum"),
]


def broad(family, code):
    d = detail()
    d["handoff"]["facts"]["material"]["value"] = family
    d["handoff"]["waste_code"] = code
    return d


@pytest.mark.parametrize("family,code,material,form", CASES)
def test_detail_narrows_and_preserves_code_with_real_catalog(family, code, material, form):
    d = broad(family, code)
    original = deepcopy(d)
    waiting = context_from_handoff(d, "C1", TreatmentSelectionIn(input_form=form), COMPANY)
    assert waiting.status == "needs_input" and waiting.route_input is None
    ctx = context_from_handoff(
        d,
        "C1",
        TreatmentSelectionIn(
            input_form=form,
            material_detail=material,
            solid_confirmed=True,
        ),
        COMPANY,
    )
    assert ctx.status == "ready" and d == original
    assert ctx.route_input["waste_code"] == code
    assert ctx.route_input["material"] == material
    result = next_step(
        NextStepRequest.model_validate(ctx.route_input),
        PlanningReference.model_validate(read_bundle("planning-reference.json")),
    )
    assert result.status == "candidates"
    assert any(o.facilities for o in result.options)
    if family == "nonferrous_scrap":
        assert {o.transition_key for o in result.options} == {
            "al-scrap-to-slab",
            "al-scrap-to-granule",
        }


@pytest.mark.parametrize(
    "family,code,chosen,state",
    [
        ("pp", "51-03-01", "pe", "solid"),
        ("plastic_packaging", "51-03-07", "unknown", "solid"),
        ("plastic_packaging", "51-03-07", "pvc", "solid"),
        ("fishing_net", "51-03-08", "pa66", "solid"),
        ("nonferrous_scrap", "51-29-02", "ferrous", "solid"),
        ("nonferrous_scrap", "51-03-01", "aluminium", "solid"),
        ("plastic_packaging", "51-03-07", "pe", "liquid"),
        ("aqua_buoy", "51-03-05", "pe", "solid"),
        ("aqua_buoy", "51-03-05", "pp", "solid"),
        ("metal_container", "51-29-04", "pe", "solid"),
    ],
)
def test_unknown_conflicting_or_liquid_cannot_make_candidates(family, code, chosen, state):
    d = broad(family, code)
    d["handoff"]["facts"]["physical_state"]["value"] = state
    ctx = context_from_handoff(
        d,
        "C1",
        TreatmentSelectionIn(
            material_detail=chosen,
            input_form="scrap",
            solid_confirmed=True,
        ),
        COMPANY,
    )
    assert ctx.status != "ready" and ctx.route_input is None


@pytest.mark.parametrize("family,code,material,form", CASES)
async def test_detail_is_persisted_separately_and_used_for_candidate_packets(
    company_client,
    fake_engine,  # noqa: F811
    db,
    monkeypatch,
    family,
    code,
    material,
    form,
):
    await replace_snapshots(db)
    d = broad(family, code)
    fake_engine.reply = httpx.Response(200, json=d)
    response = await company_client.post(
        "/api/v1/workflow/lots",
        json={
            "diagnosis_id": "C1",
            "input_form": form,
            "material_detail": material,
            "solid_confirmed": True,
            "mass_kg": 100,
            "condition": "합성 물량 상태 설명",
        },
    )
    assert response.status_code == 200, response.text
    lot = response.json()
    reread = (await company_client.get("/api/v1/workflow/lots/" + lot["id"])).json()
    assert reread["data"]["handoff"] == d["handoff"]
    assert reread["data"]["sender_confirmations"]["material_detail"] == material
    assert reread["data"]["initial"]["material"] == material
    assert reread["data"]["initial"]["waste_code"] == code
    from types import SimpleNamespace

    from app.domains.transport.workflow import process_request
    from app.domains.treatment.intake import IntakeSelection, build_intake_batch

    request = process_request(SimpleNamespace(data=reread["data"]))
    packets = build_intake_batch(
        IntakeSelection.model_validate(
            request.model_dump(exclude={"origin", "preview_transition"})
        ),
        PlanningReference.model_validate(read_bundle("planning-reference.json")),
    )
    assert packets and all(p["material"] == material and p["waste_code"] == code for p in packets)
