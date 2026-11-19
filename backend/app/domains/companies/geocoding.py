"""User-triggered site lookup. No guessed coordinates and no company writes."""

import asyncio
import math
import re
import time
from collections import OrderedDict

import httpx

from app.domains.companies.schemas import LocationResult, LocationSearchResult


class GeocodingUnavailable(Exception):
    pass


class GeocodingBusy(Exception):
    pass


_cache = OrderedDict()
_lock = asyncio.Lock()
_last_request = 0.0


def parse_results(payload, query):
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise GeocodingUnavailable()
    road = re.search(r"([가-힣0-9·]+(?:대로|로|길))\s+(\d+(?:-\d+)?)", query)
    results, seen = [], set()
    for feature in payload["features"][:30]:
        try:
            p = feature["properties"]
            geometry = feature["geometry"]
            if geometry["type"] != "Point" or p.get("countrycode", "").upper() != "KR":
                continue
            lon, lat = map(float, geometry["coordinates"])
            if not (
                math.isfinite(lat)
                and math.isfinite(lon)
                and 33 <= lat <= 39.4
                and 124.5 <= lon <= 132.35
            ):
                continue
            if p.get("osm_value") in {"bus_stop", "platform", "traffic_signals"}:
                continue
            street, number = p.get("street", ""), p.get("housenumber", "")
            if road:
                # Fuzzy provider hits on a different street/number are not this address.
                if road[1] not in {street, p.get("name")} or (number and number != road[2]):
                    continue
            address = " ".join(
                dict.fromkeys(
                    str(p[k])
                    for k in ("state", "city", "district", "locality", "street", "housenumber")
                    if p.get(k)
                )
            )
            name = str(p.get("name") or address).strip()
            if not name:
                continue
            label = f"{name} · {address}" if address and name != address else name
            precision = (
                "area"
                if p.get("type")
                in {"street", "city", "county", "state", "district", "locality", "country"}
                else "place"
            )
            if street and number:
                precision = "address"
            key = (round(lat, 6), round(lon, 6), label)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                LocationResult(
                    label=label[:800],
                    address=address[:500],
                    latitude=lat,
                    longitude=lon,
                    precision=precision,
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if len(results) == 5:
            break
    return LocationSearchResult(items=results)


async def search_kakao(query, key):
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            headers = {"Authorization": f"KakaoAK {key}"}
            response = await client.get(
                "https://dapi.kakao.com/v2/local/search/address.json",
                params={"query": query, "size": 5, "analyze_type": "exact"},
                headers=headers,
            )
            response.raise_for_status()
            documents = response.json()["documents"]
            address_result = bool(documents)
            if not documents:
                response = await client.get(
                    "https://dapi.kakao.com/v2/local/search/keyword.json",
                    params={"query": query, "size": 5},
                    headers=headers,
                )
                response.raise_for_status()
                documents = response.json()["documents"]
        items = []
        for row in documents[:5]:
            try:
                latitude, longitude = float(row["y"]), float(row["x"])
                address = row.get("road_address_name") or row.get("address_name") or ""
                label = " · ".join(filter(None, [row.get("place_name"), address]))
                items.append(
                    LocationResult(
                        label=label[:800],
                        address=address[:500],
                        latitude=latitude,
                        longitude=longitude,
                        precision=(
                            "area" if row.get("address_type") in {"REGION", "ROAD"} else "address"
                        )
                        if address_result
                        else "place",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return LocationSearchResult(provider="Kakao", attribution="© Kakao", items=items)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise GeocodingUnavailable() from exc


async def search_location(query, settings):
    global _last_request
    if not settings.company_geocoding_enabled:
        raise GeocodingUnavailable()
    query = " ".join(query.split())
    kakao_key = settings.kakao_mobility_rest_api_key.get_secret_value()
    if kakao_key:
        return await search_kakao(query, kakao_key)
    key = (settings.company_geocoding_url, query)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < 86400:
        _cache.move_to_end(key)
        return cached[1]
    if _lock.locked() or now - _last_request < 1.1:
        raise GeocodingBusy()
    async with _lock:
        _last_request = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.get(
                    settings.company_geocoding_url,
                    params={
                        "q": query,
                        "limit": 10,
                        "bbox": "124.5,33,132.35,39.4",
                        "countrycode": "KR",
                    },
                    headers={
                        "User-Agent": "SCRAP-SiteLocation/1.0 (+https://app.scrap-ai.org)",
                        "Accept-Language": "ko",
                    },
                )
                response.raise_for_status()
                result = parse_results(response.json(), query)
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocodingUnavailable() from exc
        _cache[key] = (time.monotonic(), result)
        _cache.move_to_end(key)
        while len(_cache) > 512:
            _cache.popitem(last=False)
        return result
