import uuid
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.domains.transport.models import WorkflowLot
from app.domains.transport.road_route import RoadSegmentRead, driving_segment, handoff_legs
from tests.test_pp_company_workflow import accept_receive, choose, setup_flow  # noqa: F401

A = {"latitude": 37.1714414, "longitude": 126.8447909}
B = {"latitude": 37.1454231, "longitude": 126.8145939}
C = {"latitude": 37.3, "longitude": 127.0}


@pytest.mark.parametrize("mode", ["ok", "unauthorized", "empty", "bad_geometry"])
async def test_kakao_full_road_geometry_and_failure_has_no_straight_fallback(monkeypatch, mode):
    monkeypatch.setattr(get_settings(), "kakao_mobility_rest_api_key", SecretStr("synthetic"))
    calls = []

    def handle(request):
        calls.append(request)
        if mode == "unauthorized":
            return httpx.Response(401)
        return httpx.Response(
            200,
            json={
                "routes": []
                if mode == "empty"
                else [
                    {
                        "result_code": 0,
                        "summary": {"distance": 6495, "duration": 700},
                        "sections": [
                            {
                                "roads": [
                                    {
                                        "vertexes": [126.84, 37.17, 126.83, 37.16, 126.81, 37.14]
                                        if mode == "ok"
                                        else [126.84, 37.17, 126.83]
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        route = await driving_segment("offer", (126.844, 37.171), (126.814, 37.145), client=client)
    assert calls[0].url.params["summary"] == "false"
    assert calls[0].headers["Authorization"] == "KakaoAK synthetic"
    assert route.provider == "kakao"
    if mode == "ok":
        assert route.status == "available" and len(route.coordinates) == 3
        assert route.distance_km == 6.495
    else:
        assert route.status == "unavailable" and not route.coordinates


async def test_missing_location_never_calls_provider():
    route = await driving_segment("offer", None, (126.814, 37.145))
    assert route.status == "missing_location" and not route.coordinates


def test_followup_starts_at_B_and_missing_B_does_not_invent_A_to_C():
    def offer(name, destination, **extra):
        return SimpleNamespace(
            id=name, status="received", data={"facility": {"location": destination}, **extra}
        )

    lot = SimpleNamespace(data={"initial": {"origin": A}})
    first, second = offer("AB", B), offer("BC", C)
    legs = handoff_legs(lot, [first, second])
    assert legs[1][1] == (B["longitude"], B["latitude"])
    assert legs[1][1] != legs[0][1]
    first.data["facility"]["location"] = None
    assert handoff_legs(lot, [first, second])[1][1] is None
    second.data["origin"] = B
    assert handoff_legs(lot, [first, second])[1][1] == (B["longitude"], B["latitude"])


async def test_only_lot_participants_can_read_recorded_road_route(setup_flow, db, monkeypatch):  # noqa: F811
    req, create, _, _ = setup_flow
    lot = await create("shredded")
    assert (await req("D", f"/lots/{lot['id']}/road-route", method="GET")).status_code == 404
    assert (await req("A", f"/lots/{lot['id']}/road-route", method="GET")).json()["segments"] == []
    lot = await choose(req, lot, "A", "veolia-doksan-hwaseong")
    lot = await accept_receive(req, lot, "A", "C")
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    data = deepcopy(row.data)
    data["initial"]["origin"] = A
    row.data = data
    await db.commit()
    calls = []

    async def geometry(offer_id, origin, destination):
        calls.append((origin, destination))
        return RoadSegmentRead(
            offer_id=offer_id,
            status="available",
            provider="kakao",
            coordinates=[origin, (126.83, 37.16), destination],
            distance_km=6.495,
        )

    monkeypatch.setattr("app.domains.transport.workflow.driving_segment", geometry)
    for role in ["A", "C"]:
        response = await req(role, f"/lots/{lot['id']}/road-route", method="GET")
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
        assert len(response.json()["segments"][0]["coordinates"]) == 3
    assert calls[0][0] == (A["longitude"], A["latitude"])
