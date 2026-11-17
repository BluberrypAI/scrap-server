"""Public production records are research clues, not current intake permissions."""

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import NextStepRequest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "factory_crosscheck", ROOT / "scripts/factory_registry_crosscheck.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_identity_requires_name_and_house_number_and_never_promotes():
    factory = [
        {"순번": "1", "회사명": "주식회사 동명", "공장주소": "경기 새길 38", "생산품": "PE 펠릿"},
        {"순번": "2", "회사명": "동명", "공장주소": "경기 새길 39", "생산품": "PP 분쇄품"},
        {"순번": "3", "회사명": "다른이름", "공장주소": "경기 새길 38", "생산품": "PS 펠릿"},
    ]
    queue = [
        dict(
            role="recycling",
            site_cluster="a",
            source_row="1",
            name="(주)동명",
            address="경기 새길 38 (본관)",
        ),
        dict(
            role="recycling", site_cluster="b", source_row="2", name="동명", address="경기 옛리 15"
        ),
        dict(role="recycling", site_cluster="c", source_row="3", name="동명", address=""),
        dict(
            role="recycling",
            site_cluster="d",
            source_row="4",
            name="없는회사",
            address="경기 새길 38",
        ),
        dict(
            role="transport_only",
            site_cluster="e",
            source_row="5",
            name="동명",
            address="경기 새길 38",
        ),
    ]
    rows = module.crosscheck(factory, queue)
    assert len(rows) == 4
    assert [r["match_status"] for r in rows] == [
        "exact_name_address",
        "name_only_address_unresolved",
        "name_only_address_unresolved",
        "not_found",
    ]
    assert [r["순번"] for r in rows[0]["factory_records"]] == ["1"]
    assert rows[0]["product_resin_mentions"] == ["pe"]
    assert not rows[1]["product_resin_mentions"]
    assert all(r["capability_status"] == "research_only_not_promoted" for r in rows)
    assert all(
        r["intake_form"] == r["current_permit"] == r["acceptance"] == "unknown" for r in rows
    )


@pytest.mark.parametrize(
    "product,expected",
    [
        ("PPE, PET, 폴리에틸렌글리콜", ["pet"]),
        ("폴리에틸렌테레프탈레이트", ["pet"]),
        ("PE.PP.PS 재생재료", ["pp", "pe", "ps"]),
        ("HDPE, LLDPE", ["pe"]),
        ("HIPS/GPPS", ["ps"]),
    ],
)
def test_resin_mentions_do_not_match_substrings(product, expected):
    assert module.resins(product) == expected


def test_official_archive_schema_and_ambiguous_downloads(tmp_path):
    csv = "순번,회사명,생산품,공장주소\n1,합성업체,PP 분쇄품,합성주소\n".encode("cp949")
    path = tmp_path / "factory.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("자료/등록공장현황자료_20251231.csv", csv)
    rows, digest, member = module.read_factory(path)
    assert rows[0]["생산품"] == "PP 분쇄품" and len(digest) == 64
    assert member == "자료/등록공장현황자료_20251231.csv"
    assert not (tmp_path / "자료").exists()
    path.write_bytes(b"<html>Under maintenance</html>")
    with pytest.raises(ValueError, match="required columns"):
        module.read_factory(path)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for date in ("20241231", "20251231"):
            archive.writestr(f"등록공장현황자료_{date}.csv", csv)
    path.write_bytes(stream.getvalue())
    with pytest.raises(ValueError, match="one factory CSV"):
        module.read_factory(path)


@pytest.fixture
def reference():
    return PlanningReference.model_validate(read_bundle("planning-reference.json"))


CASES = (
    [(m, form, "hcr-paju") for m in ("pp", "pe", "ps") for form in ("scrap", "flake")]
    + [(m, "scrap", "ilshin-anseong") for m in ("pp", "pe", "ps")]
    + [
        (m, "scrap", site)
        for site in ("ecoplus-yeongju", "afrochem-asan", "daejo-sangju")
        for m in ("pp", "pe")
    ]
    + [
        ("pe", "rigid", "samsungchem-miryang"),
        ("pe", "flake", "guil-hapcheon"),
        ("pp", "flake", "daesan-naju"),
        ("pp", "flake", "yongseong-gyeongsan"),
        ("pe", "flake", "yongseong-gyeongsan"),
        ("pe", "film", "dongmin-yeongcheon"),
    ]
)


@pytest.mark.parametrize("material,form,site", CASES)
def test_new_site_stays_in_the_complete_ai_candidate_batch(reference, material, form, site):
    selection = dict(material=material, input_form=form, waste_code="51-03-01")
    result = next_step(NextStepRequest(**selection), reference)
    found = [f for o in result.options for f in o.facilities if f.facility_key == site]
    assert found and all(f.evidence_basis == "published_site_process" for f in found)
    packets = build_intake_batch(IntakeSelection(**selection), reference)
    assert {f.capability_key for f in found} <= {p["capability_key"] for p in packets}
    assert not result.dispatch_approved
    facility = next(f for f in reference.facilities if f.key == site)
    assert facility.current_acceptance is facility.current_permit_scope is None


@pytest.mark.parametrize(
    "material,form,forbidden",
    [
        ("pe", "film", {"samsungchem-miryang"}),
        ("pe", "rigid", {"dongmin-yeongcheon"}),
        ("pe", "scrap", {"guil-hapcheon", "yongseong-gyeongsan"}),
        ("pp", "scrap", {"daesan-naju", "yongseong-gyeongsan"}),
        ("pe", "bale", {site for _, _, site in CASES}),
        ("ps", "bale", {site for _, _, site in CASES}),
    ],
)
def test_pipes_films_flakes_and_bales_are_not_interchangeable(reference, material, form, forbidden):
    result = next_step(
        NextStepRequest(material=material, input_form=form, waste_code="51-03-01"), reference
    )
    assert not {f.facility_key for o in result.options for f in o.facilities} & forbidden


def test_minimal_grinding_does_not_claim_washing_or_pelletising(reference):
    stages = [t for t in reference.transitions if t.key.endswith("-registered-grind")]
    assert len(stages) == 3
    for t in stages:
        assert "분쇄 가공" in t.operation_steps
        assert not any(word in " ".join(t.operation_steps) for word in ("세척", "압출", "건조"))
        assert t.output_state.endswith(("shredded", "flake"))
    for key in (
        "afrochem-asan",
        "daejo-sangju",
        "samsungchem-miryang",
        "daesan-naju",
        "yongseong-gyeongsan",
    ):
        f = next(f for f in reference.facilities if f.key == key)
        # Factory registry alone has no coordinates; independently reviewed building
        # evidence now supplies location without expanding the registered process.
        assert f.latitude is not None and f.longitude is not None
        source = next(s for s in reference.sources if s.key == f.location_source_id)
        assert source.supported_records == {"facilities": [key]}
