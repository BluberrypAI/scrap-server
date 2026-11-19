import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.domains.companies import geocoding
from tests.conftest import COMPANY_PAYLOAD

PATH = "/api/v1/companies/location-search"


async def test_kakao_address_and_place_lookup_without_response_cache(auth_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "kakao_mobility_rest_api_key", SecretStr("synthetic"))
    calls = []
    original_get = httpx.AsyncClient.get

    async def get(self, url, **kwargs):
        if str(url).startswith("/api/"):
            return await original_get(self, url, **kwargs)
        calls.append(str(url))
        documents = [
            {
                "x": "126.84",
                "y": "37.17",
                "address_name": "경기도 화성시 시험 주소",
                "address_type": "ROAD_ADDR",
            }
        ]
        if kwargs["params"]["query"] == "서울시청":
            documents = (
                []
                if "address.json" in str(url)
                else [
                    {
                        "x": "126.97",
                        "y": "37.56",
                        "place_name": "시청",
                        "address_name": "서울 시청 주소",
                    }
                ]
            )
        return httpx.Response(200, json={"documents": documents}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    for _ in range(2):
        response = await auth_client.post(PATH, json={"query": "화성시 시험 주소"})
        assert response.json()["provider"] == "Kakao"
        assert response.json()["items"][0]["precision"] == "address"
    assert len(calls) == 2
    response = await auth_client.post(PATH, json={"query": "서울시청"})
    assert response.status_code == 200
    assert response.json()["items"][0]["precision"] == "place"
    assert len(calls) == 4


def feature(**props):
    return {
        "properties": {
            "countrycode": "KR",
            "city": "서울특별시",
            "name": "서울특별시청",
            "street": "세종대로",
            "housenumber": "110",
            "type": "house",
            **props,
        },
        "geometry": {"type": "Point", "coordinates": [126.97842, 37.56679]},
    }


@pytest.fixture(autouse=True)
def isolated_geocoder(monkeypatch):
    geocoding._cache.clear()
    monkeypatch.setattr(geocoding, "_last_request", 0)
    monkeypatch.setattr(get_settings(), "company_geocoding_enabled", True)


@pytest.fixture
def upstream(monkeypatch):
    calls = []
    original_get = httpx.AsyncClient.get

    async def get(self, url, **kwargs):
        if str(url).startswith("/api/"):
            return await original_get(self, url, **kwargs)
        calls.append(kwargs)
        return httpx.Response(
            200, json={"features": [feature()]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    return calls


async def test_search_requires_login_and_valid_query(client, auth_client, upstream):
    client.cookies.clear()
    assert (await client.post(PATH, json={"query": "세종대로 110"})).status_code == 401


@pytest.mark.parametrize("query", ["", "  ", "가", "a" * 201, "서울\x00시청"])
async def test_invalid_queries_never_call_provider(auth_client, upstream, query):
    assert (await auth_client.post(PATH, json={"query": query})).status_code == 422
    assert upstream == []


async def test_search_before_company_registration_then_save_point(auth_client, upstream):
    r = await auth_client.post(PATH, json={"query": "서울특별시 중구 세종대로 110"})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "private, no-store"
    hit = r.json()["items"][0]
    assert hit["precision"] == "address"
    assert len(upstream) == 1
    assert set(upstream[0]["params"]) == {"q", "limit", "bbox", "countrycode"}
    assert "Authorization" not in upstream[0]["headers"]
    assert (
        await auth_client.post(PATH, json={"query": "서울특별시 중구 세종대로 110"})
    ).status_code == 200
    assert len(upstream) == 1  # cached query does not call upstream
    saved = await auth_client.post(
        "/api/v1/companies",
        json={
            **COMPANY_PAYLOAD,
            "site_address": "서울특별시 중구 세종대로 110",
            "site_latitude": hit["latitude"],
            "site_longitude": hit["longitude"],
        },
    )
    assert saved.status_code == 201
    company = (await auth_client.get("/api/v1/companies/me")).json()
    assert company["site_latitude"] == hit["latitude"]
    assert company["site_longitude"] == hit["longitude"]


def test_country_coordinates_road_number_and_precision():
    invalid = feature()
    invalid["geometry"]["coordinates"] = ["NaN", 37.5]
    hits = geocoding.parse_results(
        {
            "features": [
                feature(countrycode="JP"),
                invalid,
                feature(street="다른길"),
                feature(housenumber="111"),
                feature(osm_value="bus_stop"),
                feature(),
                feature(),
                feature(housenumber="", type="street"),
            ]
        },
        "세종대로 110",
    ).items
    assert len(hits) == 2
    assert [h.precision for h in hits] == ["address", "area"]
    assert geocoding.parse_results({"features": []}, "없는주소").items == []
    with pytest.raises(geocoding.GeocodingUnavailable):
        geocoding.parse_results({"oops": []}, "없는주소")


async def test_outage_is_not_empty_success(auth_client, monkeypatch):
    async def fail(*args, **kwargs):
        raise httpx.ConnectError("upstream credential should not leak")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail)
    r = await auth_client.post(PATH, json={"query": "세종대로 110"})
    assert r.status_code == 503
    assert "credential" not in r.text


async def test_rate_limit_and_disabled(auth_client, upstream, monkeypatch):
    assert (await auth_client.post(PATH, json={"query": "세종대로 110"})).status_code == 200
    r = await auth_client.post(PATH, json={"query": "세종대로 111"})
    assert r.status_code == 429 and r.headers["retry-after"] == "2"
    monkeypatch.setattr(get_settings(), "company_geocoding_enabled", False)
    assert (await auth_client.post(PATH, json={"query": "세종대로 110"})).status_code == 503
    assert len(upstream) == 1
