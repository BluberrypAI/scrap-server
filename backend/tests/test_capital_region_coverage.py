"""Regional reach must not override material, form or intermediate-output checks."""

import pytest

from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import NextStepRequest


@pytest.fixture
def reference():
    return PlanningReference.model_validate(read_bundle("planning-reference.json"))


def lookup(reference, material, form, code="51-03-01", **changes):
    return next_step(
        NextStepRequest(waste_code=code, material=material, input_form=form, **changes),
        reference,
    )


def sites(result):
    return {f.facility_key: f for o in result.options for f in o.facilities}


@pytest.mark.parametrize("form", ["scrap", "rigid", "bale", "film-bale", "shredded", "pellet"])
def test_ldpe_film_processor_is_not_promoted_to_other_pe_forms(reference, form):
    assert "sungwon-hwaseong" not in sites(lookup(reference, "pe", form))


def test_ldpe_film_extrusion_has_its_own_steps_and_needs_actual_pellets(reference):
    first = lookup(reference, "pe", "film")
    option = next(o for o in first.options if o.transition_key == "pe-film-double-extrude")
    assert "sungwon-hwaseong" in {f.facility_key for f in option.facilities}
    assert not first.can_finish and not first.dispatch_approved
    transition = next(t for t in reference.transitions if t.key == option.transition_key)
    assert not any("세척" in step for step in transition.operation_steps)
    assert any("LDPE" in check for check in transition.conditions)
    actual = lookup(
        reference,
        "pe",
        "film",
        completed_transitions=[option.transition_key],
        observed_output={"state_key": "pe-pellet", "mass_kg": 90},
    )
    assert actual.can_finish and not actual.dispatch_approved
    mismatch = lookup(
        reference,
        "pe",
        "film",
        completed_transitions=[option.transition_key],
        observed_output={"state_key": "pe-shredded", "mass_kg": 90},
    )
    assert mismatch.status == "review_required" and not mismatch.can_finish


@pytest.mark.parametrize("material", ["pp", "pe", "ps"])
def test_container_sorters_are_not_film_or_bale_receivers(reference, material):
    sorters = {"kers-hwaseong", "incheon-recycling-gojan"}
    rigid = lookup(reference, material, "rigid")
    assert sorters <= sites(rigid).keys()
    assert not sorters.intersection(sites(lookup(reference, material, "bale")))
    if material != "ps":
        assert not sorters.intersection(sites(lookup(reference, material, "film")))


@pytest.mark.parametrize("code", ["51-03-01", "51-03-07"])
def test_pet_bottle_sources_do_not_establish_bale_intake(reference, code):
    bottles = lookup(reference, "pet", "bottle", code)
    bales = lookup(reference, "pet", "bale", code)
    new = {"saerom-hwaseong-one", "kers-hwaseong", "incheon-recycling-gojan", "cwrs-hwaseong"}
    assert new <= sites(bottles).keys()
    assert not new.intersection(sites(bales))
    assert {"rm-hwaseong", "superbin-hwaseong"} <= sites(bales).keys()
    assert not bottles.dispatch_approved


def test_ferrous_shearing_requires_actual_output_and_continues_to_steelmaking(reference):
    first = lookup(reference, "ferrous", "scrap", "51-29-01")
    assert {"dongyang-gwangju", "hyundai-incheon"} <= sites(first).keys()
    second = lookup(
        reference,
        "ferrous",
        "scrap",
        "51-29-01",
        completed_transitions=["ferrous-shear"],
        observed_output={"state_key": "ferrous-prepared", "mass_kg": 90},
    )
    assert second.status == "candidates" and not second.can_finish
    assert {"hyundai-incheon", "daehan-noksan", "kisco-changwon"} <= sites(second).keys()
    mismatch = lookup(
        reference,
        "ferrous",
        "scrap",
        "51-29-01",
        completed_transitions=["ferrous-shear"],
        observed_output={"state_key": "ferrous-billet", "mass_kg": 90},
    )
    assert mismatch.status == "review_required" and not mismatch.can_finish


def test_aluminium_can_processing_does_not_skip_actual_granule_production(reference):
    first = lookup(reference, "aluminium", "can", "51-29-03")
    assert "hyundai-resource-hwaseong" in sites(first)
    assert "jmtech-gimpo" not in sites(first)
    processed = lookup(
        reference,
        "aluminium",
        "can",
        "51-29-03",
        completed_transitions=["al-can-prepare"],
        observed_output={"state_key": "al-scrap", "mass_kg": 80},
    )
    assert "jmtech-gimpo" in sites(processed) and not processed.can_finish
    final = lookup(
        reference,
        "aluminium",
        "can",
        "51-29-03",
        completed_transitions=["al-can-prepare", "al-scrap-to-granule"],
        observed_output={"state_key": "al-granule", "mass_kg": 70},
    )
    assert final.can_finish and not final.dispatch_approved


def test_same_company_different_site_does_not_supply_wrong_coordinates(reference):
    by_key = {f.key: f for f in reference.facilities}
    gojan = by_key["incheon-recycling-gojan"]
    assert gojan.address == "인천광역시 남동구 청능대로468번길 23"
    assert gojan.latitude == 37.39791914  # Not the Eumsil-ro site at 37.43486369.
    assert gojan.longitude == 126.7112538
    anseong = by_key["hwangyeong-anseong"]
    assert anseong.latitude == 37.04174375  # Not Hwaseong's same-name company.
    hyundai = by_key["hyundai-resource-hwaseong"]
    assert hyundai.latitude == 37.1837648  # Verified Sinnam-ro building, not a namesake.
    assert hyundai.location_source_id in hyundai.source_ids
    # Official embedded place markers, not the surrounding map viewport centre.
    assert by_key["dongyang-gwangju"].longitude == 127.3111563
    assert by_key["dongyang-gwangju"].latitude == 37.4202135
    assert by_key["jmtech-gimpo"].longitude == 126.5402162
    assert by_key["jmtech-gimpo"].latitude == 37.6818167


@pytest.mark.parametrize(
    "material,form,code",
    [
        ("pp", "rigid", "51-03-01"),
        ("pe", "rigid", "51-03-01"),
        ("pet", "bottle", "51-03-07"),
        ("ferrous", "scrap", "51-29-01"),
        ("aluminium", "scrap", "51-29-02"),
        ("aluminium", "can", "51-29-03"),
    ],
)
def test_origins_change_distance_without_dropping_any_review_candidate(
    reference, material, form, code
):
    baseline = sites(lookup(reference, material, form, code))
    for lat, lon in [(37.5665, 126.978), (37.1996, 126.8312), (37.7599, 126.78)]:
        result = lookup(reference, material, form, code, origin={"latitude": lat, "longitude": lon})
        current = sites(result)
        assert current.keys() == baseline.keys()
        capital = [f for f in current.values() if f.region.startswith(("경기", "인천", "서울"))]
        assert capital
        ranked = sorted(
            [f for f in current.values() if f.distance_rank], key=lambda f: f.distance_rank
        )
        assert len(ranked) <= 5
        assert [f.straight_line_distance_km for f in ranked] == sorted(
            f.straight_line_distance_km for f in ranked
        )
        assert all(f.distance_rank is None for f in current.values() if f.location is None)
        assert not result.dispatch_approved
