"""Road geometry for recorded handoffs. Never represents actual vehicle GPS."""

import math
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.domains.treatment.road_distance import ENDPOINT


class RoadSegmentRead(BaseModel):
    offer_id: str
    status: Literal["available", "unavailable", "missing_location", "not_configured"]
    provider: Literal["kakao", "osrm"] | None = None
    coordinates: list[tuple[float, float]] = Field(default_factory=list)
    distance_km: float | None = None
    duration_seconds: float | None = None
    phase: Literal["planned", "in_transit", "received"] = "planned"


class RoadRouteRead(BaseModel):
    segments: list[RoadSegmentRead]
    kind: Literal["calculated_driving_route"] = "calculated_driving_route"


def point(value):
    if not isinstance(value, dict):
        return None
    lat, lon = value.get("latitude"), value.get("longitude")
    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        for v in (lat, lon)
    ):
        return None
    return (lon, lat) if 124 <= lon <= 132 and 33 <= lat <= 39 else None


def handoff_legs(lot, offers):
    previous = lot.data.get("initial", {}).get("origin")
    legs = []
    for offer in offers:
        if offer.status not in {"pending", "conditional", "accepted", "received", "processed"}:
            continue
        destination = (offer.data.get("facility") or {}).get("location")
        origin = offer.data.get("origin") or previous
        legs.append((str(offer.id), point(origin), point(destination)))
        # A missing B coordinate must never produce an invented A→C shortcut.
        previous = destination
    return legs


def validated_path(values):
    if not isinstance(values, list) or not 2 <= len(values) <= 20000:
        raise ValueError("invalid geometry")
    path = []
    for pair in values:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("invalid coordinate")
        p = point({"longitude": pair[0], "latitude": pair[1]})
        if p is None:
            raise ValueError("invalid coordinate")
        if not path or path[-1] != p:
            path.append(p)
    if len(path) < 2:
        raise ValueError("empty geometry")
    return path


async def driving_segment(offer_id, origin, destination, *, client=None):
    result = RoadSegmentRead(offer_id=offer_id, status="missing_location")
    if origin is None or destination is None:
        return result
    settings = get_settings()
    key = settings.kakao_mobility_rest_api_key.get_secret_value()
    provider = "kakao" if key else "osrm" if settings.osrm_demo_enabled else None
    if provider is None:
        result.status = "not_configured"
        return result
    result.provider, result.status = provider, "unavailable"
    if client is None:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as session:
            return await driving_segment(offer_id, origin, destination, client=session)
    try:
        if provider == "kakao":
            response = await client.get(
                ENDPOINT,
                headers={"Authorization": f"KakaoAK {key}"},
                params={
                    "origin": f"{origin[0]},{origin[1]}",
                    "destination": f"{destination[0]},{destination[1]}",
                    "summary": "false",
                    "priority": "DISTANCE",
                    "alternatives": "false",
                    "road_details": "false",
                },
                timeout=12,
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
            if route["result_code"] != 0:
                return result
            values = []
            for section in route["sections"]:
                for road in section["roads"]:
                    vertices = road["vertexes"]
                    if len(vertices) % 2:
                        raise ValueError("odd vertices")
                    values.extend(zip(vertices[::2], vertices[1::2], strict=True))
            meters, seconds = route["summary"]["distance"], route["summary"]["duration"]
        else:
            import asyncio
            import time

            from app.domains.treatment import osrm_distance as osrm

            # Share the public demo's one-request-per-second limit with distance lookup.
            async with osrm._lock:
                await asyncio.sleep(max(0, 1.05 - (time.monotonic() - osrm._last_call)))
                osrm._last_call = time.monotonic()
                response = await client.get(
                    "https://routing.openstreetmap.de/routed-car/route/v1/driving/"
                    + ";".join(f"{p[0]},{p[1]}" for p in (origin, destination)),
                    params={
                        "overview": "full",
                        "geometries": "geojson",
                        "steps": "false",
                        "alternatives": "false",
                    },
                    timeout=12,
                )
            response.raise_for_status()
            payload = response.json()
            if payload["code"] != "Ok" or any(w["distance"] > 500 for w in payload["waypoints"]):
                return result
            route = payload["routes"][0]
            if route["geometry"]["type"] != "LineString":
                return result
            values = route["geometry"]["coordinates"]
            meters, seconds = route["distance"], route["duration"]
        path = validated_path(values)
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
            for v in (meters, seconds)
        ):
            return result
        result.coordinates = path
        result.distance_km, result.duration_seconds = meters / 1000, seconds
        result.status = "available"
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError, AttributeError):
        pass  # Provider URLs, coordinates, credentials and response bodies are not logged.
    return result
