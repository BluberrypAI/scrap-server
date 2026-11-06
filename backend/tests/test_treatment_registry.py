import json
from hashlib import sha256

from sqlalchemy import func, select

from app.domains.treatment.directory import NATIONAL_COLUMNS
from app.domains.treatment.models import TreatmentFacilityListing
from app.domains.treatment.repository import replace_snapshots


def registry_row(name, code, business, latitude):
    return {
        **dict.fromkeys(NATIONAL_COLUMNS, ""),
        "FLCT_NM": name,
        "LCTN_ROAD_NM_ADDR": "경기도 화성시 시험로 1",
        "LAT": latitude,
        "LOT": "126.90",
        "BUS_NM": business,
        "TRET_WAS_INF": code,
        "TELNO": "000-0000-0000",
    }


async def test_registry_ingests_every_row_and_filters_by_exact_code(db, client, tmp_path):
    rows = [
        registry_row("near steel", "51-29-01", "폐기물중간재활용업", "37.17"),
        registry_row("far steel", "51-29-01", "폐기물종합재활용업", "37.70"),
        registry_row("truck only", "51-29-01", "폐기물수집및운반업", "37.16"),
        registry_row("oil treatment", "06-01-03", "폐기물중간처분업", "37.16"),
    ]
    content = json.dumps(rows, ensure_ascii=False).encode()
    path = tmp_path / "registry.json"
    path.write_bytes(content)
    checksum = sha256(content).hexdigest()
    assert (await replace_snapshots(db, path, checksum))["registry_rows_imported"] == 4
    assert (await replace_snapshots(db, path, checksum))["registry_rows_imported"] == 4
    assert await db.scalar(select(func.count()).select_from(TreatmentFacilityListing)) == 4

    endpoint = "/api/treatment/facility-candidates"
    filters = {
        "waste_code": "51-29-01",
        "origin_latitude": 37.16,
        "origin_longitude": 126.90,
        "page_size": 1,
    }
    response = await client.post(endpoint, json=filters)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["backend"] == "postgresql"
    assert result["search_scope"]["registry_record_count"] == 4
    assert result["pagination"]["total_registry_candidates"] == 2
    entry = result["registry_candidates"][0]
    assert entry["research_packet"]["name"] == "near steel"
    assert "raw_record" not in entry["research_packet"]
    assert "000-0000-0000" not in response.text
    assert not entry["dispatch_approved"]
    page = await client.post(
        endpoint, json={**filters, "cursor": result["pagination"]["next_cursor"]}
    )
    assert page.json()["registry_candidates"][0]["research_packet"]["name"] == "far steel"
    oil = await client.post(endpoint, json={"waste_code": "06-01-03"})
    assert oil.json()["registry_candidates"][0]["research_packet"]["name"] == "oil treatment"


async def test_next_step_uses_seeded_reference_without_ai(db, client):
    await replace_snapshots(db)
    response = await client.post(
        "/api/treatment/next-step",
        json={"waste_code": "51-03-01", "material": "PP", "input_form": "scrap"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["backend"] == "postgresql" and payload["status"] == "candidates"
    assert payload["options"][0]["transition_key"] == "pp-prepare"
    assert payload["options"][0]["sources"]
    site = next(
        facility
        for facility in payload["options"][0]["facilities"]
        if facility["facility_key"] == "sarom-hwaseong-2"
    )
    assert site["handoff_verification"] == {
        "process": "public_evidence",
        "intake_form": "unverified",
        "intake_specification": "unverified",
        "current_permit": "unverified",
        "lot_acceptance": "unverified",
        "dispatch_status": "held",
        "simulation_available": False,
    }

    follow_up = await client.post(
        "/api/treatment/next-step",
        json={
            "waste_code": "51-03-01",
            "material": "PP",
            "input_form": "scrap",
            "completed_transitions": ["pp-prepare"],
            "observed_output": {"state_key": "pp-shredded", "mass_kg": 90},
        },
    )
    assert follow_up.status_code == 200, follow_up.text
    doksan = next(
        facility
        for option in follow_up.json()["options"]
        for facility in option["facilities"]
        if facility["facility_key"] == "veolia-doksan-hwaseong"
    )
    assert doksan["handoff_verification"]["intake_form"] == "public_example"
    assert doksan["handoff_verification"]["dispatch_status"] == "held"
