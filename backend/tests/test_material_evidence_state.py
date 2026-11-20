"""Recorded operations do not grant current acceptance or broaden material/forms."""

from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.process import facility_location, next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import NextStepRequest


def test_sihwa_flake_chip_and_goyang_can_are_reachable_with_linked_sources():
    reference = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    for material, code, form, site, transition in (
        ("pet", "51-03-01", "flake", "samyang-sihwa", "pet-flake-to-chip"),
        ("aluminium", "51-29-03", "can", "shinsung-goyang", "al-can-prepare"),
    ):
        request = dict(material=material, waste_code=code, input_form=form)
        result = next_step(NextStepRequest(**request), reference)
        option = next(o for o in result.options if o.transition_key == transition)
        assert site in {f.facility_key for f in option.facilities}
        key = f"{site}--{transition}"
        packet = next(
            p
            for p in build_intake_batch(IntakeSelection(**request), reference)
            if p["capability_key"] == key
        )
        assert packet["sources"] and packet["material"] == material
        facility = next(f for f in reference.facilities if f.key == site)
        assert facility_location(facility)[0] and facility.address and facility.location_source_id
        assert facility.current_acceptance is facility.current_permit_scope is None
        assert not result.dispatch_approved
    source = next(s for s in reference.sources if s.key == "shinsung-can-case")
    assert "만료" in source.summary and "2026-02-02" in source.summary


def test_new_sites_are_not_receivers_for_unrelated_forms():
    reference = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    for material, code, form, excluded in (
        ("aluminium", "51-29-02", "scrap", "shinsung-goyang"),
        ("pe", "51-03-01", "bale", "shinsung-goyang"),
        ("pe", "51-03-01", "bale", "samyang-sihwa"),
    ):
        result = next_step(
            NextStepRequest(material=material, waste_code=code, input_form=form), reference
        )
        assert excluded not in {f.facility_key for o in result.options for f in o.facilities}


def test_bottle_and_actual_flake_output_use_different_next_processes():
    reference = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    initial = dict(material="pet", waste_code="51-03-07", input_form="bottle")
    first = next_step(NextStepRequest(**initial), reference)
    after = next_step(
        NextStepRequest(
            **initial,
            completed_transitions=["pet-bottle-to-flake"],
            observed_output={"state_key": "pet-flake", "mass_kg": 90},
        ),
        reference,
    )
    assert "pet-flake-to-chip" not in {o.transition_key for o in first.options}
    assert "pet-flake-to-chip" in {o.transition_key for o in after.options}
    assert "pet-bottle-to-flake" not in {o.transition_key for o in after.options}
    assert after.current_state.key == "pet-flake"


def test_pe_compressed_feedstock_is_a_process_candidate_without_inventing_pellets():
    reference = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    request = dict(material="pe", waste_code="51-03-01", input_form="bale")
    result = next_step(NextStepRequest(**request), reference)
    option = next(o for o in result.options if o.transition_key == "pe-compressed-to-resin")
    assert [f.facility_key for f in option.facilities] == ["daeyoung-nonsan"]
    assert option.output_state.key == "pe-recycled-resin"
    packet = next(
        p
        for p in build_intake_batch(IntakeSelection(**request), reference)
        if p["capability_key"] == "daeyoung-nonsan--pe-compressed-to-resin"
    )
    assert packet["form"] == "bale" and len(packet["sources"]) == 3
    assert any("2021" in s["summary"] for s in packet["sources"])
    assert not next_step(
        NextStepRequest(
            **request,
            completed_transitions=[option.transition_key],
            observed_output={"state_key": option.output_state.key, "mass_kg": 90},
        ),
        reference,
    ).can_finish
    # A PE recycler is not a PS compressed-bale receiver.
    other = next_step(
        NextStepRequest(material="ps", waste_code="51-03-01", input_form="bale"), reference
    )
    assert "daeyoung-nonsan" not in {f.facility_key for o in other.options for f in o.facilities}
