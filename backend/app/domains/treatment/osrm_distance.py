"""Small, opt-in OSRM public demo adapter; single worker only."""

import asyncio
import math
import time
from collections import OrderedDict

import httpx

URL = "https://routing.openstreetmap.de/routed-car/table/v1/driving/"
_lock = asyncio.Lock()
_last_call = 0.0
_cache = OrderedDict()


def number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


async def lookup(origin, sites, client=None):
    global _last_call
    if client is None:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as session:
            return await lookup(origin, sites, session)
    sites = dict(sorted(sites.items()))
    points = [(origin.longitude, origin.latitude)] + [
        (f.location.longitude, f.location.latitude) for f in sites.values()
    ]
    key = (tuple(sites), tuple(points))
    async with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 86400:
            return dict(cached[1])
        result = {}
        entries = list(sites.items())
        for start in range(0, len(entries), 40):
            batch = entries[start : start + 40]
            coordinates = [points[0]] + [
                (f.location.longitude, f.location.latitude) for _, f in batch
            ]
            await asyncio.sleep(max(0, 1.05 - (time.monotonic() - _last_call)))
            _last_call = time.monotonic()
            try:
                response = await client.get(
                    URL + ";".join(f"{lon},{lat}" for lon, lat in coordinates),
                    params={
                        "sources": "0",
                        "destinations": ";".join(str(i) for i in range(1, len(batch) + 1)),
                        "annotations": "distance,duration",
                        "generate_hints": "false",
                    },
                    headers={
                        "User-Agent": "SCRAP-Research-Prototype/1.0 (https://github.com/BluberrypAI/scrap-server)"
                    },
                    timeout=12,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "Ok":
                    continue
                sources, destinations = data["sources"], data["destinations"]
                if not number(sources[0]["distance"]) or sources[0]["distance"] > 500:
                    continue
                distances, durations = data["distances"][0], data["durations"][0]
                for i, (site_key, _) in enumerate(batch):
                    meters, seconds = distances[i], durations[i]
                    snap = destinations[i]["distance"]
                    if (
                        number(meters)
                        and meters > 0
                        and number(seconds)
                        and number(snap)
                        and snap <= 500
                    ):
                        result[site_key] = (meters / 1000, seconds)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                break
        # Cache complete responses only; do not pin a partial outage for a day.
        if len(result) == len(entries):
            _cache[key] = (time.monotonic(), dict(result))
            _cache.move_to_end(key)
            while len(_cache) > 256:
                _cache.popitem(last=False)
        return result
