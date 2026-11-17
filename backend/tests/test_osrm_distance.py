import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.domains.treatment import osrm_distance as osrm
from app.domains.treatment.road_distance import enrich_road_distances
from app.domains.treatment.schemas import Coordinates
from tests.test_road_distance import route  # noqa: F401


@pytest.mark.parametrize("mode", ["ok", "partial", "snap", "http", "bad"])
async def test_osrm_all_candidates_and_failures(route, monkeypatch, mode):  # noqa: F811
    monkeypatch.setattr(get_settings(), "kakao_mobility_rest_api_key", SecretStr(""))
    monkeypatch.setattr(get_settings(), "osrm_demo_enabled", True)
    osrm._cache.clear()
    calls = []

    def handler(r):
        calls.append(r)
        assert r.url.params["destinations"] == "1;2;3;4;5;6;7;8"
        if mode == "http":
            return httpx.Response(429)
        if mode == "bad":
            return httpx.Response(200, json={"code": "NoTable"})
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "sources": [{"distance": 3}],
                "destinations": [{"distance": 800 if mode == "snap" else 5} for _ in range(8)],
                "distances": [
                    [None if mode == "partial" and i == 0 else (8 - i) * 1000 for i in range(8)]
                ],
                "durations": [[60] * 8],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        origin = Coordinates(latitude=37.2, longitude=126.9)
        await enrich_road_distances(route, origin, client=c)
        if mode == "ok":
            assert route.options[0].facilities[0].facility_key == "site-7"
            assert sum(f.distance_rank is not None for f in route.options[0].facilities) == 5
            await enrich_road_distances(route, origin, client=c)
            assert len(calls) == 1
        elif mode in {"snap", "http", "bad"}:
            assert all(f.road_distance_km is None for f in route.options[0].facilities)
        else:
            assert (
                next(
                    f for f in route.options[0].facilities if f.facility_key == "site-0"
                ).road_distance_km
                is None
            )
        assert len(route.options[0].facilities) == 8
