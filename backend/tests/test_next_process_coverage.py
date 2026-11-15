"""Coverage must depend on current edges, not downstream catalogue completeness."""

import pytest

from app.domains.treatment import process
from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.material_scope import FINISH_STATES, FORM_CODES
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import FacilityWebSearchRequest, NextStepRequest


@pytest.fixture
def reference():
    return PlanningReference.model_validate(read_bundle("planning-reference.json"))


def request(**changes):
    return NextStepRequest.model_validate(
        {"waste_code": "51-03-01", "material": "pp", "input_form": "scrap", **changes}
    )


def test_incomplete_downstream_does_not_hide_next_process_or_allow_completion(reference):
    reference.transitions = [t for t in reference.transitions if t.key == "pp-prepare"]
    start = process.next_step(request(), reference)
    assert [o.transition_key for o in start.options] == ["pp-prepare"]
    assert start.options[0].facilities
    for observed in (None, {"state_key": "pp-shredded", "mass_kg": 100}):
        result = process.next_step(
            request(completed_transitions=["pp-prepare"], observed_output=observed), reference
        )
        assert result.status == "no_route" and not result.can_finish
        assert result.current_state.key == "pp-shredded"


def test_no_factory_keeps_process_evidence(reference):
    reference.transitions = [t for t in reference.transitions if t.key == "pp-prepare"]
    reference.capabilities = []
    result = process.next_step(request(), reference)
    assert result.status == "no_route" and not result.can_finish
    assert result.options[0].sources and result.options[0].checks
    assert not result.options[0].facilities and not result.dispatch_approved


def test_preview_budget_does_not_hide_any_current_choice(reference, monkeypatch):
    before = process.next_step(request(), reference)
    monkeypatch.setattr(process, "MAX_EXPANSIONS", 0)
    monkeypatch.setattr(process, "MAX_PLANS", 1)
    after = process.next_step(request(), reference)
    assert after.options == before.options
    assert after.process_previews_truncated and after.status == "candidates"


@pytest.mark.parametrize("completed", [["pp-clean"], ["pp-prepare", "pp-compound"], ["pet-wash"]])
def test_disconnected_history_rejected(reference, completed):
    with pytest.raises(TreatmentError, match="완료한 공정"):
        process.next_step(request(completed_transitions=completed), reference)


@pytest.mark.parametrize("material,form", FORM_CODES)
def test_every_registered_direct_edge_is_returned_for_each_supported_entry(
    reference, material, form
):
    result = process.next_step(
        request(material=material, input_form=form, waste_code=FORM_CODES[material, form][0]),
        reference,
    )
    starts = {
        s.key
        for s in reference.states
        if s.material == material and s.is_entry and form in s.input_forms
    }
    expected = {t.key for t in reference.transitions if t.input_state in starts}
    assert {o.transition_key for o in result.options} == expected
    assert not result.dispatch_approved


def test_each_actual_output_exposes_all_its_outgoing_processes(reference):
    states = {s.key: s for s in reference.states}
    for transition in reference.transitions:
        material = states[transition.input_state].material
        entry = next(((m, f) for m, f in FORM_CODES if m == material), None)
        if entry is None:
            continue
        result = process.next_step(
            request(
                material=material,
                input_form=entry[1],
                waste_code=FORM_CODES[entry][0],
                completed_transitions=[transition.key],
                observed_output={"state_key": transition.output_state, "mass_kg": 100},
            ),
            reference,
        )
        expected = {
            t.key for t in reference.transitions if t.input_state == transition.output_state
        }
        assert {o.transition_key for o in result.options} == expected, transition.key
        assert result.can_finish == (transition.output_state in FINISH_STATES[material])


def test_search_packet_uses_catalogue_context_for_every_active_process(reference):
    states = {s.key: s for s in reference.states}
    for transition in reference.transitions:
        state = states[transition.input_state]
        if state.material not in FINISH_STATES:
            continue
        for form in state.input_forms or ["washed"]:
            packet = process.web_search_packet(
                FacilityWebSearchRequest(
                    transition_key=transition.key,
                    input_form=form,
                    region="capital",
                ),
                reference,
            )
            assert packet["material"] == state.material
            assert packet["process_label"] == transition.label
            assert packet["operation_steps"] == transition.operation_steps
            assert packet["waste_code"] is None and packet["recycling_types"] is None


def test_eps_foam_must_be_densified_before_an_ingot_receiver(reference):
    first = process.next_step(
        request(material="eps", input_form="foam", waste_code="51-03-06"), reference
    )
    assert first.status == "candidates" and not first.can_finish
    by_key = {o.transition_key: o for o in first.options}
    assert set(by_key) == {"eps-foam-densify", "eps-foam-volume-reduce"}
    assert not by_key["eps-foam-densify"].facilities
    assert [f.facility_key for f in by_key["eps-foam-volume-reduce"].facilities] == ["hanul-ulju"]
    assert by_key["eps-foam-volume-reduce"].output_state.key == "eps-reduced"
    assert not any(
        f.facility_key == "ecops-yeongcheon" for o in first.options for f in o.facilities
    )
    reduced = process.next_step(
        request(
            material="eps",
            input_form="foam",
            waste_code="51-03-06",
            completed_transitions=["eps-foam-volume-reduce"],
            observed_output={"state_key": "eps-reduced", "mass_kg": 100},
        ),
        reference,
    )
    assert reduced.status == "no_route" and not reduced.can_finish
    assert not reduced.options
    after = process.next_step(
        request(
            material="eps",
            input_form="foam",
            waste_code="51-03-06",
            completed_transitions=["eps-foam-densify"],
            observed_output={"state_key": "eps-ingot", "mass_kg": 100},
        ),
        reference,
    )
    assert after.status == "candidates" and not after.can_finish
    assert any(f.facility_key == "ecops-yeongcheon" for o in after.options for f in o.facilities)
