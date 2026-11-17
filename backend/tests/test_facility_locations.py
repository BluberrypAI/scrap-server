"""Verified building coordinates must reach maps without implying intake approval."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import Coordinates, NextStepRequest


def test_backfilled_locations_have_scoped_provenance_and_leave_acceptance_unknown():
    ref = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    sources = {s.key: s for s in ref.sources}
    audit = json.loads(
        (
            Path(__file__).parents[2] / "docs/registry-screen/facility-locations-20261117.json"
        ).read_text(encoding="utf8")
    )
    expected = {r["facility_key"]: r for r in audit}
    assert len(expected) == 30
    for f in ref.facilities:
        if f.key not in expected:
            continue
        entry = expected[f.key]
        assert (f.latitude, f.longitude) == (entry["latitude"], entry["longitude"])
        assert f.address == entry["address"]
        assert sources[f.location_source_id].url == entry["coordinate_url"]
        assert f.key in sources[f.location_source_id].supported_records["facilities"]
        assert f.current_acceptance is None and f.current_permit_scope is None


@pytest.mark.parametrize("broken", ["other-facility-source", "missing-point"])
def test_location_citation_cannot_reference_other_facility_or_missing_point(broken):
    data = read_bundle("planning-reference.json")
    located = [f for f in data["facilities"] if f.get("location_source_id")]
    if broken == "other-facility-source":
        located[0]["location_source_id"] = located[1]["location_source_id"]
    else:
        located[0]["latitude"] = located[0]["longitude"] = None
    with pytest.raises(ValidationError, match="Unlinked location source"):
        PlanningReference.model_validate(data)


def test_steel_followup_exposes_three_mapped_sites_and_location_citations():
    ref = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    # The concrete completed transition is chosen from the actual ferrous graph.
    step = next(t for t in ref.transitions if t.output_state == "ferrous-prepared")
    result = next_step(
        NextStepRequest(
            waste_code="51-29-01",
            material="ferrous",
            input_form="scrap",
            completed_transitions=[step.key],
            observed_output={"state_key": "ferrous-prepared", "mass_kg": 950},
            origin=Coordinates(latitude=37.15, longitude=126.88),
        ),
        ref,
    )
    sites = {f.facility_key: f for o in result.options for f in o.facilities}
    assert {"hyundai-incheon", "kisco-changwon", "daehan-noksan"} <= sites.keys()
    for key in ("hyundai-incheon", "kisco-changwon", "daehan-noksan"):
        assert sites[key].location is not None
        assert sites[key].location_source_url.startswith("https://dorojuso.kr/")
    assert not result.dispatch_approved
