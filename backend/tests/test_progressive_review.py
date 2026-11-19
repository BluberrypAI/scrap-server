import base64
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.domains.treatment import progressive
from app.domains.treatment.intake import IntakeSelection, build_intake_batch
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import PlanningReference, read_bundle
from app.domains.treatment.schemas import Coordinates, NextStepRequest


@pytest.fixture
def pipeline(monkeypatch):
    ref = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    selection = IntakeSelection(waste_code="51-03-01", material="pp", input_form="scrap")
    packets = build_intake_batch(selection, ref)
    request = NextStepRequest(**selection.model_dump())
    state = {
        "photos": 0,
        "keys": [],
        "batches": [],
        "public_batches": [],
        "progress": [],
        "outcomes": {},
        "photo_signature": "photo-v1",
        "comparison_signature": "compare-v1",
        "visibility": "clear",
    }
    ordered_keys = sorted(p["capability_key"] for p in packets)

    async def roads(result, origin):
        by_key = {f.capability_key: f for option in result.options for f in option.facilities}
        if state.get("same_site"):
            first, second = state["same_site"]
            by_key[second].facility_key = by_key[first].facility_key
        for option in result.options:
            for f in option.facilities:
                f.road_distance_status = (
                    "unavailable" if f.capability_key in state.get("unrouted", []) else "available"
                )
                f.road_distance_km = ordered_keys.index(f.capability_key) + 1

    def handle(request):
        import json

        if request.url.path.endswith("/review-config"):
            return httpx.Response(
                200,
                json={
                    "version": "progressive-review-v1",
                    "photo_signature": state["photo_signature"],
                    "comparison_signature": state["comparison_signature"],
                    "public_signature": state.get("public_signature", "public-v1"),
                },
            )
        body = json.loads(request.content)
        if request.url.path.endswith("/photo-observations"):
            state["photos"] += 1
            return httpx.Response(
                200,
                json={
                    "status": "reviewed",
                    "signature": state["photo_signature"],
                    "observations": [
                        {
                            "photo_id": p["photo_id"],
                            "description": "합성 관찰",
                            "visibility": state["visibility"],
                        }
                        for p in body["photos"]
                    ],
                },
            )
        if "lot_context" not in body:
            state["public_batches"].append(body["candidates"])
            rows = {}
            for p in body["candidates"]:
                key = p["capability_key"]
                finding = state.get("public_outcomes", {}).get(key, "form_mentioned")
                rows[key] = {
                    "status": "needs_evidence" if finding == "insufficient" else "reviewed",
                    "finding": finding,
                    "next_check": "공개 투입 근거",
                    "source": {k: p["sources"][0][k] for k in ("publisher", "url", "locator")}
                    if p["sources"] and finding != "insufficient"
                    else None,
                    "quote": "합성 공개 PP 투입 근거" if finding != "insufficient" else None,
                }
                process_match = state.get("process_matches", {}).get(key)
                if process_match is not None:
                    rows[key].update(
                        status="reviewed",
                        process_match=process_match,
                        process_quote="공개 공정: PP 재생 펠렛 생산",
                    )
            return httpx.Response(200, json={"results": rows})
        assert not body["lot_context"]["photos"]  # Do not retransmit raw images for comparisons.
        keys = [p["capability_key"] for p in body["candidates"]]
        state["keys"].extend(keys)
        state["batches"].append(keys)
        rows = {}
        for key in keys:
            finding = state["outcomes"].get(key, "form_mentioned")
            rows[key] = {
                "status": "needs_evidence" if finding == "insufficient" else "reviewed",
                "finding": finding,
                "next_check": "반입 조건 확인",
                "lot_review": {
                    "status": "reviewed",
                    "observation_method": "isolated_vision",
                    "photo_observations": body["photo_observations"],
                },
            }
            if key in state.get("process_matches", {}):
                rows[key].update(status="reviewed", process_match=state["process_matches"][key])
        return httpx.Response(200, json={"results": rows})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        progressive.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    monkeypatch.setattr(progressive, "enrich_road_distances", roads)
    settings = SimpleNamespace(
        ai_base_url="https://route.test", scrap_intake_service_token=SecretStr("test")
    )
    context = {
        "state_key": "pp-scrap",
        "mass_kg": 1000,
        "condition": "합성 시험 물량",
        "photos": [
            {
                "photo_id": "photo-1",
                "data_url": "data:image/jpeg;base64,"
                + base64.b64encode(b"\xff\xd8\xfftest\xff\xd9").decode(),
            }
        ],
    }

    state["context"] = context

    async def run(cache=None, values=None, public_store=None):
        async def report(phase, **data):
            state["progress"].append({"phase": phase, **data})

        return await progressive.review_nearby(
            values or deepcopy(packets),
            next_step(request, ref),
            Coordinates(latitude=37.1, longitude=126.8),
            settings,
            context,
            cache or {},
            report,
            public_store=public_store,
        )

    return state, packets, ordered_keys, run


async def test_nearest_five_stop_without_reviewing_the_rest(pipeline):
    state, packets, keys, run = pipeline
    reviewed, selection, _ = await run()
    assert state["photos"] == 1
    assert state["keys"] == keys[:5]
    assert len(selection["selected_keys"]) == 5
    assert len(selection["deferred_keys"]) == len(packets) - 5
    assert len(reviewed.results) == 5
    assert max(map(len, state["batches"])) == 3
    assert [p["phase"] for p in state["progress"]][:2] == ["road_distance", "photo_observation"]


async def test_restriction_and_insufficient_evidence_backfill_in_distance_order(pipeline):
    state, _, keys, run = pipeline
    state["outcomes"] = {keys[0]: "restriction_mentioned", keys[2]: "insufficient"}
    _, selection, _ = await run()
    assert state["keys"] == keys[:7]
    assert len(selection["selected_keys"]) == 5
    assert selection["restricted_keys"] == [keys[0]]
    assert selection["needs_evidence_keys"] == [keys[2]]


async def test_one_answer_change_reuses_photo_and_other_site_judgments(pipeline):
    state, packets, keys, run = pipeline
    _, _, cache = await run()
    state["keys"].clear()
    updated = deepcopy(packets)
    next(p for p in updated if p["capability_key"] == keys[0])["intake_answers"] = {"clean": "yes"}
    _, selection, _ = await run(cache, updated)
    assert state["photos"] == 1
    assert state["keys"] == keys[:1]
    assert selection["cache_hits"] == 5  # One photo observation plus four unchanged candidates.


async def test_non_waste_image_stops_before_any_facility_model_call(pipeline):
    state, _, _, run = pipeline
    state["visibility"] = "not_waste"
    reviewed, selection, _ = await run()
    assert state["photos"] == 1 and not state["keys"]
    assert not selection["selected_keys"]
    assert all(
        r.lot_review.photo_observations[0].visibility == "not_waste"
        for r in reviewed.results.values()
    )


async def test_no_proven_sites_does_not_invent_five_and_reuses_negative_evidence(pipeline):
    state, _, keys, run = pipeline
    state["outcomes"] = dict.fromkeys(keys, "insufficient")
    _, selection, cache = await run()
    assert not selection["selected_keys"] and len(selection["needs_evidence_keys"]) == len(keys)
    assert state["keys"] == keys
    state["keys"].clear()
    await run(cache)
    assert not state["keys"] and state["photos"] == 1


async def test_model_change_invalidates_both_observations_and_comparisons(pipeline):
    state, _, keys, run = pipeline
    _, _, cache = await run()
    state["keys"].clear()
    state.update(photo_signature="photo-v2", comparison_signature="compare-v2")
    await run(cache)
    assert state["photos"] == 2 and state["keys"] == keys[:5]


async def test_same_site_in_two_processes_counts_once_and_replacement_is_ranked(pipeline):
    state, _, keys, run = pipeline
    state["same_site"] = keys[:2]
    _, selection, _ = await run()
    assert len(selection["selected_keys"]) == 5
    assert state["keys"] == [keys[0], *keys[2:6]]
    assert keys[1] in selection["deferred_keys"]


async def test_unrouted_candidate_is_preserved_but_never_ranked_by_straight_line(pipeline):
    state, _, keys, run = pipeline
    state["unrouted"] = keys[:2]
    _, selection, _ = await run()
    assert state["keys"] == keys[2:7]
    assert selection["distance_unknown_keys"] == keys[:2]
    assert selection["selected_keys"] == keys[2:7]


async def test_new_lot_reuses_public_negatives_but_reviews_its_own_state(pipeline, session_factory):
    from app.domains.treatment.public_cache import PublicReviewStore

    state, packets, keys, run = pipeline
    state["public_outcomes"] = {key: "insufficient" for key in keys[1:]}
    store = PublicReviewStore(session_factory)
    _, first, _ = await run(public_store=store)
    assert first["lot_model_calls"] == 1 and first["public_model_calls"] > 0
    assert first["selected_keys"] == keys[:1]
    assert all("intake_answers" not in p for batch in state["public_batches"] for p in batch)
    public_calls = len(state["public_batches"])
    state["keys"].clear()
    state["context"]["condition"] = "다른 기업의 새 물량이며 상태 설명도 다릅니다."
    _, second, cache = await run(public_store=store)
    assert len(state["public_batches"]) == public_calls
    assert second["public_cache_hits"] == len(packets)
    assert second["public_model_calls"] == 0 and second["lot_model_calls"] == 1
    assert state["keys"] == keys[:1] and state["photos"] == 2
    _, third, _ = await run(cache, public_store=store)
    assert third["lot_model_calls"] == third["public_model_calls"] == third["model_calls"] == 0
    # An expired public record must invalidate a still-matching private lot result too.
    from app.domains.treatment.models import TreatmentSnapshot
    from app.domains.treatment.public_cache import KIND

    async with session_factory() as db:
        row = await db.get(TreatmentSnapshot, KIND)
        values = deepcopy(row.payload)
        for value in values.values():
            value["expires_at"] = "2000-01-01T00:00:00+00:00"
        row.payload = values
        await db.commit()
    _, expired, _ = await run(cache, public_store=store)
    assert expired["public_model_calls"] > 0 and expired["lot_model_calls"] == 1


async def test_public_cache_changes_only_for_public_inputs(pipeline, session_factory):
    from app.domains.treatment.public_cache import PublicReviewStore

    state, packets, keys, run = pipeline
    store = PublicReviewStore(session_factory)
    await run(public_store=store)
    updated = deepcopy(packets)
    next(p for p in updated if p["capability_key"] == keys[0])["intake_answers"] = {
        "private": "secret-answer"
    }
    _, reused, _ = await run(values=updated, public_store=store)
    assert reused["public_model_calls"] == 0 and reused["public_cache_hits"] == 5
    changed = next(p for p in updated if p["capability_key"] == keys[0])
    changed["sources"][0]["summary"] += " 자료 개정."
    _, refreshed, _ = await run(values=updated, public_store=store)
    assert refreshed["public_model_calls"] == 1 and refreshed["public_cache_hits"] == 4
    state["public_signature"] = "public-v2"
    _, new_model, _ = await run(public_store=store)
    assert new_model["public_model_calls"] == 2 and new_model["public_cache_hits"] == 0


async def test_process_match_is_sufficient_without_exact_feedstock_intake_quote(
    pipeline, session_factory
):
    from app.domains.treatment.public_cache import PublicReviewStore

    state, _, keys, run = pipeline
    state["public_outcomes"] = state["outcomes"] = dict.fromkeys(keys, "insufficient")
    state["process_matches"] = dict.fromkeys(keys, "matched")
    reviewed, selection, _ = await run(public_store=PublicReviewStore(session_factory))
    assert selection["selected_keys"] == keys[:5]
    assert all(reviewed.results[k].finding == "insufficient" for k in keys[:5])


async def test_unknown_or_mismatched_process_is_not_inquiry_candidate(pipeline, session_factory):
    from app.domains.treatment.public_cache import PublicReviewStore

    state, _, keys, run = pipeline
    state["process_matches"] = dict.fromkeys(keys, "matched")
    state["process_matches"].update({keys[0]: "unverified", keys[1]: "mismatch"})
    _, selection, _ = await run(public_store=PublicReviewStore(session_factory))
    assert selection["selected_keys"] == keys[2:7]
    assert keys[1] in selection["mismatch_keys"]
