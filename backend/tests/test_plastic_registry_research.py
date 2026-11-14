"""Primary-source curation boundaries, registry screening and next-step regressions."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.domains.treatment.conditions import questionnaire
from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import NextStepRequest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "registry_screen", ROOT / "scripts/plastic_registry_screen.py"
)
screen_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen_module)


def test_registry_screen_does_not_promote_code_or_equipment_into_resin_capability():
    raw = [
        dict(
            FLCT_NM="동명업체",
            LCTN_ROAD_NM_ADDR="주소1",
            BUS_NM="폐기물종합재활용업",
            TRET_WAS_INF="51-03-01",
            FLCT_EQU_NM="용융",
        ),
        dict(
            FLCT_NM="동명업체",
            LCTN_ROAD_NM_ADDR="주소2",
            BUS_NM="폐기물수집및운반업",
            TRET_WAS_INF="폐플라스틱",
        ),
        dict(FLCT_NM="금속", BUS_NM="폐기물종합재활용업", TRET_WAS_INF="51-29-03"),
        dict(BUS_NM="폐기물중간처분업", TRET_WAS_INF="폐비닐"),
        dict(BUS_NM="폐기물중간처분업", TRET_WAS_INF="폐비닐"),
        dict(TRET_WAS_INF="151-03-01"),
    ]
    rows = screen_module.screen(raw)
    assert [r["source_row"] for r in rows] == [1, 2, 4, 5]
    assert [r["role"] for r in rows] == ["recycling", "transport_only", "disposal", "disposal"]
    assert len({r["site_cluster"] for r in rows}) == 4
    assert all(r["material"] == r["input_form"] == r["acceptance"] == "unknown" for r in rows)
    assert all(r["capability_status"] == "unverified_directory_record" for r in rows)
    assert not any("TELNO" in r for r in rows)


@pytest.fixture
def reference():
    return PlanningReference.model_validate(read_bundle("planning-reference.json"))


@pytest.mark.parametrize(
    "material,code,form,site",
    [
        ("pe", "51-03-07", "film", "saramtech-nonsan"),
        ("pa66", "51-03-01", "flake", "yangil-incheon"),
        ("pa6", "51-03-08", "net", "yangil-incheon"),
        ("pp", "51-03-01", "flake", "jinyoung-hwaseong"),
        ("pe", "51-03-01", "shredded", "jinyoung-hwaseong"),
        ("pp", "51-03-01", "scrap", "youone-incheon"),
        ("pe", "51-03-01", "rigid", "youone-incheon"),
        ("pet", "51-03-07", "bottle", "dakyeong-busan"),
        ("pe", "51-03-01", "scrap", "dakyeong-busan"),
        ("pp", "51-03-01", "rigid", "dakyeong-busan"),
        ("pe", "51-03-01", "scrap", "nuvotec-munmak"),
        ("pp", "51-03-01", "rigid", "joongil-incheon"),
        ("pvc", "51-03-03", "rigid", "pureum-yangju"),
    ],
)
def test_new_sites_are_candidates_and_in_complete_ai_batch(reference, material, code, form, site):
    selection = dict(material=material, waste_code=code, input_form=form)
    result = next_step(NextStepRequest(**selection), reference)
    found = [f for o in result.options for f in o.facilities if f.facility_key == site]
    assert found and all(f.evidence_basis == "published_site_process" for f in found)
    batch = build_intake_batch(IntakeSelection(**selection), reference)
    assert {f.capability_key for f in found} <= {p["capability_key"] for p in batch}
    assert not result.dispatch_approved
    q = questionnaire(reference, site, material)
    assert q["recipient_confirmation_required"] and not q["dispatch_approved"]
    assert q["facts"] and any(item["source"] for item in q["questions"])


def test_promotion_does_not_claim_ldpe_film_or_bale_intake(reference):
    caps = [c for c in reference.capabilities if c.facility == "npc-chemical-hwaseong"]
    assert len(caps) == 2 and all(c.basis == "published_site_process" for c in caps)
    for form in ("film", "bale"):
        result = next_step(
            NextStepRequest(waste_code="51-03-01", material="pe", input_form=form), reference
        )
        assert not any(
            f.facility_key == "npc-chemical-hwaseong" for o in result.options for f in o.facilities
        )
    raw = next_step(
        NextStepRequest(waste_code="51-03-01", material="pp", input_form="scrap"), reference
    )
    assert not any(f.facility_key == "jinyoung-hwaseong" for o in raw.options for f in o.facilities)


@pytest.mark.parametrize(
    "material,code", [("pe", "51-03-01"), ("pe", "51-03-07"), ("ps", "51-03-01")]
)
def test_bales_remain_honest_gaps_not_flakes_or_eps_ingots(reference, material, code):
    result = next_step(
        NextStepRequest(waste_code=code, material=material, input_form="bale"), reference
    )
    # A literature-backed process can be shown, but has no documented Korean site.
    assert result.status == "no_route" and not result.can_finish
    assert result.options and not any(option.facilities for option in result.options)
    assert all(
        "plasticsrecyclers.eu" in source.url
        for option in result.options
        for source in option.sources
    )
    assert "결속재" in result.message and "반입 확인 자료" in result.message
    assert not result.dispatch_approved


def test_all_original_hypotheses_have_explicit_review_decisions(reference):
    audit = json.loads((ROOT / "docs/registry-screen/role-review.json").read_text(encoding="utf8"))
    assert len(audit["rows"]) == 21
    current = {c.key: c for c in reference.capabilities}
    assert sum(r["after"] == "published_site_process" for r in audit["rows"]) == 2
    for row in audit["rows"]:
        assert current[row["capability_key"]].basis == row["after"]
        assert set(row["source_ids"]) <= {s.key for s in reference.sources}
    assert all(
        c.basis == "site_role_hypothesis"
        for c in reference.capabilities
        if c.facility.startswith("cntk-")
    )


def test_building_pvc_is_not_wallpaper_or_ordinary_resin(reference):
    wrong_code = next_step(
        NextStepRequest(waste_code="51-03-01", material="pvc", input_form="rigid"), reference
    )
    assert wrong_code.status == "unsupported"
    wallpaper = next_step(
        NextStepRequest(waste_code="51-03-03", material="pvc", input_form="wallpaper"), reference
    )
    assert not any(
        f.facility_key == "pureum-yangju" for o in wallpaper.options for f in o.facilities
    )
    film = next_step(
        NextStepRequest(waste_code="51-03-01", material="pp", input_form="film"), reference
    )
    assert not any(f.facility_key == "joongil-incheon" for o in film.options for f in o.facilities)


@pytest.mark.parametrize("material", ["pe", "ps"])
def test_bale_output_from_b_cannot_jump_to_a_flake_receiver(reference, material):
    selection = dict(
        waste_code="51-03-01",
        material=material,
        input_form="scrap",
        completed_transitions=[material + "-sort-bale"],
        observed_output={"state_key": material + "-bale", "mass_kg": 100},
    )
    result = next_step(NextStepRequest(**selection), reference)
    assert result.status == "no_route" and not result.can_finish
    assert not any(o.facilities for o in result.options)
    assert "반입 확인 자료" in result.message
    assert not build_intake_batch(IntakeSelection(**selection), reference)
    selection["observed_output"]["mass_kg"] = 0
    assert "0 kg" in next_step(NextStepRequest(**selection), reference).message


def test_new_address_joins_do_not_invent_coordinates(reference):
    links = read_bundle("facility-evidence-links.json")["rows"]
    for key in ["yangil-incheon", "youone-incheon"]:
        row = next(r for r in links if r["facility_key"] == key)
        assert row["status"] == "exact_site_match" and row["registry_rows"]
    for key in ["saramtech-nonsan", "jinyoung-hwaseong", "dakyeong-busan", "nuvotec-munmak"]:
        f = next(f for f in reference.facilities if f.key == key)
        assert f.latitude is f.longitude is None
