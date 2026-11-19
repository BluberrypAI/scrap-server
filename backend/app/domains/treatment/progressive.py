"""Distance-ordered, five-site review with independent photo and candidate caches."""

from copy import deepcopy
from hashlib import sha256

import httpx

from app.domains.treatment.intake import (
    IntakeBatchResult,
    IntakeResult,
    LotReview,
    PhotoObservation,
)
from app.domains.treatment.public_cache import public_finding, public_packet
from app.domains.treatment.reference import digest
from app.domains.treatment.road_distance import enrich_road_distances

TARGET = 5
POLICY = "road-top-five-v1"


class ReviewUnavailable(RuntimeError):
    pass


async def review_nearby(
    packets, result, origin, settings, lot_context, cache, report, *, public_store=None
):
    """All candidates remain accounted for; only selected nearby sites need AI work."""
    cache = deepcopy(cache)
    entries = cache.setdefault("candidates", {})
    results = {}
    selected = set()
    selected_sites = set()
    counters = {
        "completed": 0,
        "total": len(packets),
        "selected": 0,
        "target": TARGET,
        "model_calls": 0,
        "cache_hits": 0,
        "public_cache_hits": 0,
        "public_model_calls": 0,
        "lot_model_calls": 0,
    }

    async def progress(phase):
        await report(phase, **counters, cache=cache)

    await progress("road_distance")
    await enrich_road_distances(result, origin)
    facilities = {f.capability_key: f for o in result.options for f in o.facilities}
    packet_map = {p["capability_key"]: p for p in packets}
    ordered = sorted(
        (key for key in packet_map if facilities[key].road_distance_status == "available"),
        key=lambda key: (facilities[key].road_distance_km, facilities[key].facility_key, key),
    )
    distance_unknown = [key for key in packet_map if key not in set(ordered)]
    config = None
    observations = []
    text_context = {k: v for k, v in lot_context.items() if k != "photos"}
    photos = lot_context.get("photos", [])
    text_context["photos"] = []
    text_context["photo_ids"] = [p["photo_id"] for p in photos]

    async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
        headers = {
            "Authorization": "Bearer " + settings.scrap_intake_service_token.get_secret_value()
        }
        root = settings.ai_base_url.rstrip("/") + "/treatment"

        async def request(method, path, body=None):
            try:
                response = await client.request(method, root + path, headers=headers, json=body)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                raise ReviewUnavailable(
                    "AI 검토 서비스에 연결하지 못했어요. 다시 시도해 주세요."
                ) from None

        if not settings.ai_base_url or not settings.scrap_intake_service_token.get_secret_value():
            raise ReviewUnavailable("AI 검토 연결 설정을 확인해 주세요.")
        config = await request("GET", "/review-config")
        if public_store is not None and not config.get("public_signature"):
            raise ReviewUnavailable("처리경로 AI의 공개 근거 캐시 버전을 업데이트해 주세요.")
        if config.get("version") != "progressive-review-v1":
            raise ReviewUnavailable("처리경로 AI를 새 버전으로 업데이트해 주세요.")
        await progress("photo_observation")
        photo_key = digest(
            {
                "photos": [
                    [p["photo_id"], sha256(p["data_url"].encode()).hexdigest()] for p in photos
                ],
                "signature": config["photo_signature"],
            }
        )
        photo_cache = cache.get("photo", {})
        if photos:
            if photo_cache.get("key") == photo_key:
                observations = photo_cache["observations"]
                counters["cache_hits"] += 1
            else:
                data = await request("POST", "/photo-observations", {"photos": photos})
                counters["model_calls"] += 1
                if (
                    data.get("status") != "reviewed"
                    or data.get("signature") != config["photo_signature"]
                ):
                    raise ReviewUnavailable("사진 확인을 완료하지 못했어요. 다시 시도해 주세요.")
                rows = [PhotoObservation.model_validate(row) for row in data["observations"]]
                if len(rows) != len(photos) or {r.photo_id for r in rows} != set(
                    text_context["photo_ids"]
                ):
                    raise ReviewUnavailable("사진 확인 결과를 검증하지 못했어요.")
                observations = [r.model_dump() for r in rows]
                cache["photo"] = {"key": photo_key, "observations": observations}
        if any(o["visibility"] == "not_waste" for o in observations):
            for key in packet_map:
                results[key] = IntakeResult(
                    status="needs_evidence",
                    next_check="실제 물량 사진으로 교체해 주세요.",
                    lot_review=LotReview(
                        status="reviewed",
                        photo_observations=observations,
                        observation_method="isolated_vision",
                    ),
                )
            await progress("photo_rejected")
        elif ordered:
            remaining = list(ordered)
            while remaining and len(selected_sites) < TARGET:
                # A site may implement several processes; do not count it twice.
                wave, rest, wave_sites = [], [], set()
                slots = TARGET - len(selected_sites)
                for key in remaining:
                    site = facilities[key].facility_key
                    if site in selected_sites:
                        continue
                    if len(wave_sites) < slots and site not in wave_sites:
                        wave.append(key)
                        wave_sites.add(site)
                    else:
                        rest.append(key)
                remaining = rest
                if not wave:
                    break
                for start in range(0, len(wave), 3):
                    keys = wave[start : start + 3]
                    shared_public = {}
                    if public_store is not None:
                        await progress("public_evidence")
                        shared_public = await public_store.get_many(
                            [public_packet(packet_map[key]) for key in keys],
                            config["public_signature"],
                        )
                        counters["public_cache_hits"] += len(shared_public)
                        counters["cache_hits"] += len(shared_public)
                    pending = []
                    fingerprints = {}
                    for key in keys:
                        fingerprints[key] = digest(
                            {
                                "packet": packet_map[key],
                                "lot": text_context,
                                "observations": observations,
                                "photo": photo_key,
                                "signature": config["comparison_signature"],
                            }
                        )
                        previous = entries.get(key, {})
                        public_current = public_store is None or (
                            key in shared_public
                            and previous.get("public_key")
                            == digest(shared_public[key].model_dump())
                        )
                        if previous.get("key") == fingerprints[key] and public_current:
                            results[key] = IntakeResult.model_validate(previous["result"])
                            counters["cache_hits"] += 1
                        else:
                            pending.append(key)
                    await progress("facility_review")
                    public_results = None
                    if pending and public_store is not None:
                        await progress("public_evidence")
                        public_packets = [public_packet(packet_map[key]) for key in pending]
                        signature = config["public_signature"]
                        public_results = {
                            key: shared_public[key] for key in pending if key in shared_public
                        }
                        missing = [
                            p for p in public_packets if p["capability_key"] not in public_results
                        ]
                        if missing:
                            data = await request("POST", "/intake-reviews", {"candidates": missing})
                            fresh = IntakeBatchResult.model_validate(data).results
                            counters["public_model_calls"] += 1
                            counters["model_calls"] += 1
                            await public_store.put_many(missing, signature, fresh)
                            public_results.update(fresh)
                        usable = []
                        for key in pending:
                            value = public_results.get(
                                key,
                                IntakeResult(
                                    status="model_unavailable",
                                    next_check=packet_map[key]["next_check"],
                                ),
                            )
                            if value.status == "reviewed" and value.finding == "form_mentioned":
                                usable.append(key)
                            else:
                                results[key] = value
                        pending = usable
                        await progress("public_evidence")
                    await progress("facility_review")
                    if pending:
                        data = await request(
                            "POST",
                            "/intake-reviews",
                            {
                                "candidates": [packet_map[key] for key in pending],
                                "lot_context": text_context,
                                "photo_observations": observations,
                                "observation_signature": config["photo_signature"],
                                **(
                                    {
                                        "public_signature": config["public_signature"],
                                        "public_findings": {
                                            key: public_finding(
                                                packet_map[key], public_results[key]
                                            )
                                            for key in pending
                                        },
                                    }
                                    if public_results is not None
                                    else {}
                                ),
                            },
                        )
                        batch = IntakeBatchResult.model_validate(data)
                        counters["model_calls"] += len(pending)
                        counters["lot_model_calls"] += len(pending)
                        for key in pending:
                            value = batch.results.get(
                                key,
                                IntakeResult(
                                    status="model_unavailable",
                                    next_check=packet_map[key]["next_check"],
                                ),
                            )
                            results[key] = value
                            if value.status in {"reviewed", "needs_evidence"} and (
                                value.lot_review and value.lot_review.status == "reviewed"
                            ):
                                entries[key] = {
                                    "key": fingerprints[key],
                                    "result": value.model_dump(),
                                    **(
                                        {"public_key": digest(public_results[key].model_dump())}
                                        if public_results is not None
                                        else {}
                                    ),
                                }
                    for key in keys:
                        value = results[key]
                        if (
                            value.status == "reviewed"
                            and value.finding == "form_mentioned"
                            and value.lot_review
                            and value.lot_review.status == "reviewed"
                        ):
                            site = facilities[key].facility_key
                            if site not in selected_sites:
                                selected.add(key)
                                selected_sites.add(site)
                    counters["completed"] = len(results)
                    counters["selected"] = len(selected_sites)
                    await progress("facility_review")

    selected_order = sorted(
        selected,
        key=lambda key: (facilities[key].road_distance_km, facilities[key].facility_key, key),
    )
    ranks = {facilities[key].facility_key: index + 1 for index, key in enumerate(selected_order)}
    for key, facility in facilities.items():
        facility.distance_rank = ranks.get(facility.facility_key) if key in selected else None
    selection = {
        "policy": POLICY,
        "target": TARGET,
        "selected_keys": selected_order,
        "examined_count": counters["completed"],
        "eligible_count": len(packets),
        "model_calls": counters["model_calls"],
        "cache_hits": counters["cache_hits"],
        "public_cache_hits": counters["public_cache_hits"],
        "public_model_calls": counters["public_model_calls"],
        "lot_model_calls": counters["lot_model_calls"],
        "deferred_keys": [k for k in ordered if k not in results],
        "distance_unknown_keys": distance_unknown,
        "needs_evidence_keys": [k for k, r in results.items() if r.status == "needs_evidence"],
        "unavailable_keys": [k for k, r in results.items() if r.status == "model_unavailable"],
        "restricted_keys": [k for k, r in results.items() if r.finding == "restriction_mentioned"],
    }
    # Retain examined alternatives separately; they are never presented as approved sites.
    selection["other_options"] = [
        {
            **o.model_dump(mode="json"),
            "facilities": [
                f.model_dump(mode="json") for f in o.facilities if f.capability_key not in selected
            ],
        }
        for o in result.options
        if any(f.capability_key not in selected for f in o.facilities)
    ]
    for option in result.options:
        option.facilities = [f for f in option.facilities if f.capability_key in selected]
    result.options = [o for o in result.options if o.facilities]
    return IntakeBatchResult(results=results), selection, cache
