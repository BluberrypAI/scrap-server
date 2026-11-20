import asyncio
from copy import deepcopy

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.domains.treatment import road_distance as road
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import Coordinates, NextStepRequest


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(get_settings(), "kakao_mobility_rest_api_key", SecretStr("test-key"))
    ref = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    result = next_step(
        NextStepRequest(waste_code="51-03-01", material="pp", input_form="scrap"), ref
    )
    template = result.options[0].facilities[0]
    result.options = [result.options[0]]
    result.options[0].facilities = [
        template.model_copy(
            update={
                "facility_key": f"site-{i}",
                "capability_key": f"cap-{i}",
                "location": Coordinates(latitude=37 + i / 100, longitude=127),
                "straight_line_distance_km": i + 1,
                "distance_rank": i + 1,
                "evidence_basis": "published_site_process",
            }
        )
        for i in range(8)
    ]
    return result


async def apply(result, handler, origin=None):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await road.enrich_road_distances(
            result, origin or Coordinates(latitude=37.2, longitude=126.9), client=client
        )


async def test_every_site_queried_once_and_road_rank_differs_from_straight_line(route):
    calls, active, peak = [], 0, 0
    route.options.append(deepcopy(route.options[0]))

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(request)
        await asyncio.sleep(0)
        i = round((float(request.url.params["destination"].split(",")[1]) - 37) * 100)
        active -= 1
        return httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "result_code": 0,
                        "summary": {
                            "distance": (8 - i) * 1000,
                            "duration": 60,
                        },
                    }
                ]
            },
        )

    await apply(route, handler)
    assert len(calls) == 8 and peak <= 3
    assert all(r.headers["Authorization"] == "KakaoAK test-key" for r in calls)
    assert all(r.url.params["origin"] == "126.9,37.2" for r in calls)
    assert all(r.url.params["priority"] == "DISTANCE" for r in calls)
    for option in route.options:
        assert len(option.facilities) == 8
        assert option.facilities[0].facility_key == "site-7"
        assert option.facilities[0].straight_line_distance_km == 8
        assert option.facilities[0].road_distance_km == 1
        assert sum(f.distance_rank is not None for f in option.facilities) == 5


async def test_company_material_candidate_is_not_penalized_for_unconfirmed_site_scope(route):
    route.options[0].facilities[0].evidence_basis = "site_role_hypothesis"

    def handler(request):
        is_near = request.url.params["destination"] == "127.0,37.0"
        return httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "result_code": 0,
                        "summary": {"distance": 1000 if is_near else 5000, "duration": 60},
                    }
                ]
            },
        )

    await apply(route, handler)
    nearest = route.options[0].facilities[0]
    assert nearest.facility_key == "site-0" and nearest.distance_rank == 1
    assert nearest.evidence_basis == "site_role_hypothesis"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"routes": []},
        {"routes": [None]},
        {"routes": [{"result_code": 104}]},
        {"routes": [{"result_code": 0, "summary": {"distance": -3, "duration": 20}}]},
        {"routes": [{"result_code": 0, "summary": {"distance": True, "duration": 20}}]},
    ],
)
async def test_bad_or_missing_route_never_becomes_road_distance(route, payload):
    await apply(route, lambda r: httpx.Response(200, json=payload))
    assert all(f.road_distance_km is None for f in route.options[0].facilities)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_failure_preserves_all_candidates(route, status):
    await apply(route, lambda r: httpx.Response(status))
    assert len(route.options[0].facilities) == 8
    assert all(f.road_distance_km is None for f in route.options[0].facilities)


async def test_partial_success_does_not_rank_unknown_road_by_straight_line(route):
    def handler(r):
        assert r.url.params["origin"] == "127.4,36.4"
        return httpx.Response(
            200,
            json={"routes": [{"result_code": 0, "summary": {"distance": 20000, "duration": 900}}]}
            if r.url.params["destination"] == "127.0,37.07"
            else {},
        )

    await apply(route, handler, Coordinates(latitude=36.4, longitude=127.4))
    ranked = [f for f in route.options[0].facilities if f.distance_rank]
    assert [f.facility_key for f in ranked] == ["site-7"]


async def test_no_key_or_origin_makes_no_external_call(route, monkeypatch):
    def forbidden(r):
        pytest.fail("No external request expected")

    monkeypatch.setattr(get_settings(), "kakao_mobility_rest_api_key", SecretStr(""))
    await apply(route, forbidden)
    assert route.options[0].facilities[0].road_distance_status == "not_configured"
    monkeypatch.setattr(get_settings(), "kakao_mobility_rest_api_key", SecretStr("test-key"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        await road.enrich_road_distances(route, None, client=client)
    assert all(f.road_distance_status == "missing_location" for f in route.options[0].facilities)


async def test_total_timeout_is_bounded_and_results_remain(route, monkeypatch):
    monkeypatch.setattr(road, "TOTAL_TIMEOUT", 0.01)

    async def handler(r):
        await asyncio.sleep(1)
        return httpx.Response(500)

    await apply(route, handler)
    assert len(route.options[0].facilities) == 8
    assert all(f.road_distance_km is None for f in route.options[0].facilities)
