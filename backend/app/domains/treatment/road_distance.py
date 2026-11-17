"""Optional driving distances; failed lookups never become road estimates."""

import asyncio
import math
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings

ENDPOINT = "https://apis-navi.kakaomobility.com/v1/directions"
TOTAL_TIMEOUT = 20


def distance_version():
    return (
        "kakao-driving-v1"
        if get_settings().kakao_mobility_rest_api_key.get_secret_value()
        else "osrm-demo-v1"
        if get_settings().osrm_demo_enabled
        else "straight-line-v1"
    )


def positive_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


async def enrich_road_distances(result, origin, *, client=None):
    """Only alter distance metadata/ranks, preserving every candidate and review."""
    facilities = [f for o in result.options for f in o.facilities]
    key = get_settings().kakao_mobility_rest_api_key.get_secret_value()
    osrm = not key and get_settings().osrm_demo_enabled
    for f in facilities:
        f.road_distance_km = None
        f.road_duration_seconds = None
        f.road_distance_provider = None
        f.road_distance_checked_at = None
        f.road_distance_status = "not_configured" if not key and not osrm else "missing_location"
    if (not key and not osrm) or origin is None or not facilities:
        return result
    sites = {}
    for f in facilities:
        if f.location is not None:
            sites.setdefault(f.facility_key, f)
            f.road_distance_status = "unavailable"
    if not sites:
        return result
    if osrm:
        from app.domains.treatment.osrm_distance import lookup

        distances = await lookup(origin, sites, client)
    else:
        if client is None:
            async with httpx.AsyncClient(timeout=6, follow_redirects=False) as session:
                return await enrich_road_distances(result, origin, client=session)
        semaphore = asyncio.Semaphore(3)
        distances = {}
        circuit_open = False

        async def fetch(site_key, facility):
            nonlocal circuit_open
            async with semaphore:
                if circuit_open:
                    return
                point = facility.location
                try:
                    response = await client.get(
                        ENDPOINT,
                        headers={"Authorization": f"KakaoAK {key}"},
                        params={
                            "origin": f"{origin.longitude},{origin.latitude}",
                            "destination": f"{point.longitude},{point.latitude}",
                            "summary": "true",
                            "priority": "DISTANCE",
                            "alternatives": "false",
                            "road_details": "false",
                        },
                        timeout=6,
                    )
                    if response.status_code in {401, 403, 429}:
                        circuit_open = True
                        return
                    response.raise_for_status()
                    payload = response.json()
                    routes = payload.get("routes") if isinstance(payload, dict) else None
                    if (
                        not isinstance(routes, list)
                        or not routes
                        or not isinstance(routes[0], dict)
                    ):
                        return
                    route = routes[0]
                    summary = route.get("summary")
                    if route.get("result_code") != 0 or not isinstance(summary, dict):
                        return
                    meters, seconds = summary.get("distance"), summary.get("duration")
                    if positive_number(meters) and positive_number(seconds):
                        distances[site_key] = (meters / 1000, seconds)
                except (httpx.HTTPError, ValueError, TypeError):
                    # Do not log request URLs, coordinates, key or provider response bodies.
                    return

        tasks = [asyncio.create_task(fetch(k, f)) for k, f in sites.items()]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=TOTAL_TIMEOUT)
        except TimeoutError:
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    checked = datetime.now(UTC).isoformat()
    for f in facilities:
        if f.location is not None:
            f.road_distance_provider = "osrm" if osrm else "kakao"
            f.road_distance_checked_at = checked
        if f.facility_key in distances:
            f.road_distance_km, f.road_duration_seconds = distances[f.facility_key]
            f.road_distance_status = "available"
    if distances:
        # Unknown road distances must not compete with known road distances as straight lines.
        ranked = sorted(
            (k for k in distances if sites[k].evidence_basis == "published_site_process"),
            key=lambda k: (distances[k][0], k),
        )[:5]
        ranks = {k: index + 1 for index, k in enumerate(ranked)}
        for option in result.options:
            for f in option.facilities:
                f.distance_rank = ranks.get(f.facility_key)
            option.facilities.sort(
                key=lambda f: (
                    f.evidence_basis != "published_site_process",
                    f.road_distance_km if f.road_distance_status == "available" else math.inf,
                    f.facility_key,
                )
            )
    return result
