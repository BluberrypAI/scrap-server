import json
from hashlib import sha256
from types import SimpleNamespace

import httpx
from pydantic import SecretStr
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
    types = {"free": ["R-10", "R-3-3"], "analysis": ["R-10-1", "R-8-2"]}
    response = await client.post(
        "/api/treatment/next-step",
        json={
            "waste_code": "51-03-01",
            "material": "PP",
            "input_form": "scrap",
            "recycling_types": types,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["backend"] == "postgresql" and payload["status"] == "candidates"
    assert payload["options"][0]["transition_key"] == "pp-prepare"
    assert payload["options"][0]["web_search_form"] == "scrap"
    assert payload["options"][0]["recycling_types"] == {
        "free": ["R-10"],
        "analysis": ["R-10-1"],
        "unmarked": [],
    }
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
    preview = await client.post(
        "/api/treatment/next-step",
        json={
            "waste_code": "51-03-01",
            "material": "PP",
            "input_form": "scrap",
            "preview_transition": "pp-prepare",
        },
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["basis"] == "expected_output" and not plan["dispatch_approved"]
    assert any(
        facility["facility_key"] == "veolia-doksan-hwaseong"
        for option in plan["options"]
        for facility in option["facilities"]
    )

    follow_up = await client.post(
        "/api/treatment/next-step",
        json={
            "waste_code": "51-03-01",
            "material": "PP",
            "input_form": "scrap",
            "completed_transitions": ["pp-prepare"],
            "observed_output": {"state_key": "pp-shredded"},
            "recycling_types": types,
        },
    )
    assert follow_up.status_code == 200, follow_up.text
    assert all(
        option["recycling_types"] is None and option["web_search_form"] == "shredded"
        for option in follow_up.json()["options"]
    )
    doksan = next(
        facility
        for option in follow_up.json()["options"]
        for facility in option["facilities"]
        if facility["facility_key"] == "veolia-doksan-hwaseong"
    )
    assert doksan["handoff_verification"]["intake_form"] == "public_example"
    assert doksan["handoff_verification"]["dispatch_status"] == "held"
    empty = await client.post(
        "/api/treatment/next-step",
        json={
            "waste_code": "51-03-01",
            "material": "PP",
            "input_form": "scrap",
            "completed_transitions": ["pp-prepare"],
            "observed_output": {"state_key": "pp-shredded", "mass_kg": 0},
        },
    )
    assert empty.json()["status"] == "no_route"


async def test_web_search_requires_auth_and_a_compatible_public_query(db, client, auth_client):
    await replace_snapshots(db)
    endpoint = "/api/treatment/facility-web-search"
    request = {"transition_key": "pp-prepare", "input_form": "scrap", "region": "capital"}
    auth_cookies = dict(client.cookies)
    client.cookies.clear()
    assert (await client.post(endpoint, json=request)).status_code == 401
    client.cookies.update(auth_cookies)
    assert (
        await auth_client.post(endpoint, json={**request, "input_form": "pellet"})
    ).status_code == 400
    assert (
        await auth_client.post(endpoint, json={**request, "origin_latitude": 37})
    ).status_code == 422
    response = await auth_client.post(endpoint, json=request)
    assert response.json() == {"status": "unavailable", "leads": [], "dispatch_approved": False}


async def test_every_first_handoff_candidate_is_sent_for_review(db, auth_client, monkeypatch):
    from app.domains.treatment import intake, router

    await replace_snapshots(db)
    selection = {
        "waste_code": "51-03-01",
        "material": "PP",
        "input_form": "scrap",
        "recycling_types": {"free": ["R-10", "R-9-3"]},
    }
    route = await auth_client.post("/api/treatment/next-step", json=selection)
    expected = {
        item["capability_key"]
        for option in route.json()["options"]
        for item in option["facilities"]
    }
    assert len(expected) >= 3

    def upstream(request):
        assert request.url.path == "/treatment/intake-reviews"
        assert request.headers["authorization"] == "Bearer local-test-token"
        packets = json.loads(request.content)["candidates"]
        assert {packet["capability_key"] for packet in packets} == expected
        assert all(packet["recycling_types"]["free"] == ["R-10"] for packet in packets)
        assert all(packet["form"] == "scrap" and "origin" not in packet for packet in packets)
        source_free = next(p for p in packets if p["site"].startswith("새롬이엔지"))
        assert source_free["sources"] == []
        return httpx.Response(
            200,
            json={
                "results": {
                    packet["capability_key"]: {
                        "status": "needs_evidence",
                        "next_check": packet["next_check"],
                    }
                    for packet in packets[:-1]
                },
            },
        )

    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(intake.httpx, "AsyncClient", lambda **_: upstream_client)
    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: SimpleNamespace(
            ai_base_url="http://ai.test", scrap_intake_service_token=SecretStr("local-test-token")
        ),
    )
    response = await auth_client.post("/api/treatment/intake-reviews", json=selection)
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert set(results) == expected
    assert sum(row["status"] == "model_unavailable" for row in results.values()) == 1
    assert all(row["dispatch_approved"] is False for row in results.values())


async def test_follow_up_reviews_actual_output_without_original_classification(db):
    from app.domains.treatment.intake import IntakeSelection, build_intake_batch
    from app.domains.treatment.repository import read_reference

    await replace_snapshots(db)
    reference, _ = await read_reference(db)
    selection = {
        "waste_code": "51-03-01",
        "material": "PP",
        "input_form": "scrap",
        "recycling_types": {"free": ["R-10"]},
        "completed_transitions": ["pp-prepare"],
    }
    assert not build_intake_batch(IntakeSelection(**selection), reference)
    mismatch = {"state_key": "pp-pellet", "mass_kg": 90}
    assert not build_intake_batch(IntakeSelection(**selection, observed_output=mismatch), reference)
    packets = build_intake_batch(
        IntakeSelection(**selection, observed_output={"state_key": "pp-shredded", "mass_kg": 90}),
        reference,
    )
    assert {packet["capability_key"] for packet in packets} == {
        "bgf-yesan--pp-clean",
        "veolia-doksan-hwaseong--pp-shredded-to-pellet",
    }
    for packet in packets:
        assert "PP 파쇄품" in packet["form"]
        assert packet["waste_code"] is None and packet["recycling_types"] == {}
        assert "observed_output" not in packet and "completed_transitions" not in packet
