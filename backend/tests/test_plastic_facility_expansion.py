"""Public-reference coverage and synthetic company workflows; not permit certification."""
# ruff: noqa: F811 - pytest injects the imported shared fixture by name.

import pytest

from app.domains.treatment.classification import PROFILES
from app.domains.treatment.conditions import questionnaire
from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import NextStepRequest
from tests.test_pp_company_workflow import (
    accept_receive,
    choose,
    save_output,
    setup_flow,  # noqa: F401 - shared isolated company fixture
    use_handoff,
)

CASES = [
    ("pp", "51-03-01", "scrap", "daewoon-naju", "pp-pellet"),
    ("pp", "51-03-07", "film", "youngshin-naju", "pp-pellet"),
    ("pp", "51-03-01", "bale", "veolia-doksan-hwaseong", "pp-pellet"),
    ("pe", "51-03-01", "film", "youngshin-naju", "pe-pellet"),
    ("pe", "51-03-07", "rigid", "daewoon-naju", "pe-pellet"),
    ("pet", "51-03-07", "bottle", "yuil-yangsan", "pet-flake"),
    ("pet", "51-03-01", "bale", "yuil-busan", "pet-flake"),
    ("abs", "51-03-01", "flake", "changmaec-seongju", "abs-pellet"),
    ("ps", "51-03-01", "shredded", "changmaec-seongju", "ps-pellet"),
    ("pvc", "51-03-03", "wallpaper", "sungji-hwaseong", "pvc-recovered"),
    ("pvc", "51-03-03", "rigid", "pureum-yangju", "pvc-powder"),
    ("pp", "51-03-01", "rigid", "joongil-incheon", "pp-pellet"),
    ("eps", "51-03-06", "ingot", "ecops-yeongcheon", "eps-ps-pellet"),
    ("pa6", "51-03-08", "net", "netspa-busan", "pa6-resin"),
    ("pa66", "51-03-01", "flake", "changmaec-seongju", "pa66-compound"),
    ("pcabs", "51-03-01", "flake", "changmaec-seongju", "pcabs-compound"),
]


@pytest.fixture
def reference():
    return PlanningReference.model_validate(read_bundle("planning-reference.json"))


@pytest.mark.parametrize("material,code,form,facility,output", CASES)
def test_documented_site_is_an_immediate_candidate_and_in_every_ai_batch(
    reference, material, code, form, facility, output
):
    selection = dict(waste_code=code, material=material, input_form=form)
    result = next_step(NextStepRequest(**selection), reference)
    rows = [f for o in result.options for f in o.facilities]
    assert result.status == "candidates"
    assert any(f.facility_key == facility for f in rows)
    assert all(f.sources for f in rows)
    assert not result.dispatch_approved
    packets = build_intake_batch(IntakeSelection(**selection), reference)
    assert {p["capability_key"] for p in packets} == {f.capability_key for f in rows}
    assert all(p["material"] == material and p["form"] == form for p in packets)
    questions = questionnaire(reference, facility, material)["questions"]
    assert "moisture" in {q["key"] for q in questions}


@pytest.mark.parametrize(
    "material,code,form",
    [
        ("PVC", "51-03-01", "wallpaper"),
        ("PVC", "51-03-03", "pipe"),
        ("EPS", "51-03-06", "loose_foam"),
        ("PS", "51-03-06", "ingot"),
        ("PA66", "51-03-08", "net"),
        ("PA", "51-03-01", "flake"),
        ("PC", "51-03-01", "flake"),
        ("PLA", "51-03-01", "scrap"),
        ("mixed", "51-03-01", "scrap"),
        ("PP", "51-03-08", "scrap"),
    ],
)
def test_no_generic_resin_fallback(reference, material, code, form):
    result = next_step(
        NextStepRequest(waste_code=code, material=material, input_form=form), reference
    )
    assert result.status == "unsupported" and not result.options


def test_company_products_do_not_certify_each_of_its_factories(reference):
    candidates = [c for c in reference.capabilities if c.facility.startswith("cntk-")]
    assert len(candidates) == 12
    assert all(c.basis == "site_role_hypothesis" for c in candidates)
    for f in reference.facilities:
        assert f.current_acceptance is f.current_permit_scope is None
        assert f.current_price_krw_per_kg is f.current_available_capacity_kg is None
    links = read_bundle("facility-evidence-links.json")["rows"]
    unresolved = {r["facility_key"] for r in links if r["status"] == "not_linked"}
    assert {"daewoon-naju", "veolia-dh-yongin"} <= unresolved
    for f in reference.facilities:
        if f.key in unresolved:
            assert f.latitude is f.longitude is None


def test_form_unknown_stays_unknown_and_new_questionnaire_profiles_are_not_invented(reference):
    for c in reference.capabilities:
        if c.facility in {"pne-eumseong", "greenpol-cheonan"}:
            assert c.input_profile.form_examples == []
    assert set(PROFILES) == {
        "pp-injection-scrap",
        "pp-shredded",
        "pe-film",
        "pet-bottle",
        "aluminium-beverage-can",
    }


def test_future_facility_growth_cannot_hide_immediate_candidates(reference):
    request = NextStepRequest(waste_code="51-03-01", material="pp", input_form="scrap")
    before = next_step(request, reference)
    future = next(c for c in reference.capabilities if c.transition == "pp-pelletise")
    reference.capabilities.extend(
        future.model_copy(update={"key": f"synthetic-future-{i}"}) for i in range(2500)
    )
    after = next_step(request, reference)
    assert after.model_dump() == before.model_dump()
    # Also no fixed top-5 truncation in the AI packets for CURRENT candidates.
    current = next(c for c in reference.capabilities if c.transition == "pp-prepare")
    reference.capabilities.extend(
        current.model_copy(update={"key": f"synthetic-current-{i}"}) for i in range(120)
    )
    packets = build_intake_batch(
        IntakeSelection(waste_code="51-03-01", material="pp", input_form="scrap"), reference
    )
    assert {f"synthetic-current-{i}" for i in range(120)} <= {p["capability_key"] for p in packets}


@pytest.mark.parametrize("material,code,form,facility,output", CASES)
async def test_new_material_company_acceptance_qr_output_and_finish(
    setup_flow, db, material, code, form, facility, output
):
    req, create, actors, packets = setup_flow
    role = "C" if facility == "veolia-doksan-hwaseong" else "B"
    bindings = [] if role == "C" else [(facility, role)]
    await use_handoff(db, actors, material, code, bindings)
    lot = await create(form)
    lot = await choose(req, lot, "A", facility)
    lot = await accept_receive(req, lot, "A", role)
    lot = await save_output(req, lot, role, output, 900)
    finished = await req(
        role,
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "SYNTHETIC-PLASTIC-OUTPUT",
            "intended_use": "합성 테스트용 회수 원료",
            "confirmed": True,
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"
    assert (await req("A", f"/lots/{lot['id']}", method="GET")).json()["status"] == "completed"
    assert all(p["material"] == material for p in packets[0]["packets"])
    assert packets[0]["lot_context"]["mass_kg"] == 1000


@pytest.mark.parametrize(
    "material,code,form,b,c,intermediate,output",
    [
        (
            "pp",
            "51-03-01",
            "scrap",
            "veolia-dh-yongin",
            "veolia-doksan-hwaseong",
            "pp-bale",
            "pp-pellet",
        ),
        (
            "pe",
            "51-03-01",
            "film",
            "sarom-hwaseong-2",
            "greenpol-cheonan",
            "pe-shredded",
            "pe-pellet",
        ),
        ("pet", "51-03-07", "bottle", "hrm-cheongju", "yuil-busan", "pet-bale", "pet-flake"),
        ("pp", "51-03-01", "scrap", "ecoplus-yeongju", "hcr-paju", "pp-shredded", "pp-pellet"),
        (
            "pe",
            "51-03-01",
            "rigid",
            "samsungchem-miryang",
            "guil-hapcheon",
            "pe-shredded",
            "pe-pellet",
        ),
        ("ps", "51-03-01", "scrap", "ilshin-anseong", "hcr-paju", "ps-flake", "ps-pellet"),
    ],
)
async def test_actual_b_output_drives_c_review_and_qr(
    setup_flow, db, material, code, form, b, c, intermediate, output
):
    req, create, actors, packets = setup_flow
    bindings = [
        (f, role)
        for f, role in [(b, "B"), (c, "C")]
        if f not in {"sarom-hwaseong-2", "veolia-doksan-hwaseong"}
    ]
    await use_handoff(db, actors, material, code, bindings)
    lot = await choose(req, await create(form), "A", b)
    lot = await accept_receive(req, lot, "A", "B")
    assert (
        await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    ).status_code == 409
    lot = await save_output(req, lot, "B", intermediate, 950)
    lot = await choose(req, lot, "B", c)
    assert packets[-1]["lot_context"]["state_key"] == intermediate
    assert packets[-1]["lot_context"]["mass_kg"] == 950
    lot = await accept_receive(req, lot, "B", "C")
    lot = await save_output(req, lot, "C", output, 900)
    done = await req(
        "C",
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "SYNTHETIC-TWO-HOPS",
            "intended_use": "합성 테스트 회수 원료",
            "confirmed": True,
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
