"""Public-reference coverage and synthetic company workflows; not permit certification."""
# ruff: noqa: F811 - pytest injects the imported shared fixture by name.

import pytest

from app.domains.treatment.classification import PROFILES
from app.domains.treatment.conditions import questionnaire
from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.material_scope import PLASTICS
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
    ("ferrous", "51-29-01", "scrap", "daehan-noksan", "ferrous-billet"),
    ("ferrous", "51-29-01", "scrap", "kisco-changwon", "ferrous-billet"),
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
    assert ("moisture" in {q["key"] for q in questions}) == (material in PLASTICS)


@pytest.mark.parametrize(
    "material,code,form",
    [
        ("PVC", "51-03-01", "wallpaper"),
        ("PVC", "51-03-03", "pipe"),
        ("XPS", "51-03-06", "foam"),
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
    for c in candidates:
        documented = c.facility == "cntk-hwaseong" and c.transition.endswith("-prepare")
        assert c.basis == ("published_site_process" if documented else "site_role_hypothesis")
        if documented:
            assert "mcee-cntk-hwaseong-202512" in c.source_ids
    for f in reference.facilities:
        assert f.current_acceptance is f.current_permit_scope is None
        assert f.current_price_krw_per_kg is f.current_available_capacity_kg is None
    links = read_bundle("facility-evidence-links.json")["rows"]
    unresolved = {r["facility_key"] for r in links if r["status"] == "not_linked"}
    assert {"daewoon-naju", "veolia-dh-yongin"} <= unresolved
    for f in reference.facilities:
        if f.key in unresolved:
            # A failed registry join must not borrow a namesake's coordinates.
            # A separately cited, official address marker is independent evidence.
            if f.location_source_id:
                source = next(s for s in reference.sources if s.key == f.location_source_id)
                assert source.supported_records == {"facilities": [f.key]}
                assert source.acquisition == "public-address-page-exact-building-manual-review"
                assert f.latitude is not None and f.longitude is not None
                continue
            location_sources = [
                s
                for s in reference.sources
                if s.key in f.source_ids and s.key.endswith("-published-location")
            ]
            if location_sources:
                assert f.latitude is not None and f.longitude is not None
                assert all(
                    f.key in s.supported_records.get("facilities", []) for s in location_sources
                )
                assert all("지도 주소 마커" in s.locator for s in location_sources)
            else:
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


@pytest.mark.parametrize("output_state", ["eps-reduced", "eps-ingot"])
async def test_eps_reduction_site_receives_foam_but_c_needs_output_evidence(
    setup_flow, db, output_state
):
    req, create, actors, packets = setup_flow
    await use_handoff(db, actors, "eps", "51-03-06", [("hanul-ulju", "B")])
    lot = await choose(req, await create("foam"), "A", "hanul-ulju")
    sent = next(
        p
        for p in packets[-1]["packets"]
        if p["capability_key"] == "hanul-ulju--eps-foam-volume-reduce"
    )
    assert sent["material"] == "eps" and sent["form"] == "foam"
    lot = await accept_receive(req, lot, "A", "B")
    lot = await save_output(req, lot, "B", output_state, 950)
    assert lot["status"] == ("processed" if output_state == "eps-reduced" else "review_required")
    # A public description of "reduced material" is not proof of an ingot. Neither
    # an unqualified output nor a different declared output grants automatic dispatch.
    result = await req("B", f"/lots/{lot['id']}/candidates", {"revision": lot["revision"]})
    if output_state == "eps-ingot":
        assert result.status_code == 409
    else:
        assert result.status_code == 200, result.text
        lot = result.json()
        assert lot["review"]["next_step"]["status"] == "no_route"
    done = await req(
        "B",
        f"/lots/{lot['id']}/finish",
        {
            "revision": lot["revision"],
            "reference": "SYNTHETIC-EPS-REDUCTION",
            "intended_use": "미확인 감용물",
            "confirmed": True,
        },
    )
    assert done.status_code == 409
