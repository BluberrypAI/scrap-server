import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from app.domains.transport import review_jobs, workflow
from app.domains.transport.models import WorkflowLot
from tests.test_pp_company_workflow import detail, setup_flow  # noqa: F401


async def test_enqueue_is_fast_idempotent_and_isolated_then_worker_persists_progress(
    setup_flow,  # noqa: F811
    db,
    session_factory,
    monkeypatch,  # noqa: F811
):
    req, create, _, _ = setup_flow
    lot = await create()
    path = f"/lots/{lot['id']}/review-jobs"
    denied = await req("D", path, {"revision": lot["revision"]})
    assert denied.status_code == 404
    first = await req("A", path, {"revision": lot["revision"]})
    assert first.status_code == 202
    first = first.json()
    job = first["review_progress"]
    assert job["status"] == "queued" and job["phase"] == "queued"
    second = (await req("A", path, {"revision": lot["revision"]})).json()
    assert second["review_progress"]["id"] == job["id"]
    assert first["revision"] == lot["revision"]

    async def run(*args, report, **kwargs):
        await report("road_distance", total=14, completed=0)
        snapshot = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
        assert snapshot["review_progress"]["phase"] == "road_distance"
        await report(
            "facility_review",
            total=14,
            completed=3,
            selected=2,
            cache={"photo": {"key": "test", "observations": []}},
        )

    monkeypatch.setattr(workflow, "run_candidate_review", run)
    assert await review_jobs.run_next(session_factory, engine=object())
    latest = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    assert latest["review_progress"]["status"] == "completed"
    assert latest["review_progress"]["completed"] == 3
    assert "_review_cache" not in latest["data"]
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]), populate_existing=True)
    assert row.data["_review_cache"]["photo"]["key"] == "test"


async def test_expired_job_is_interrupted_without_automatic_model_retry(
    setup_flow,  # noqa: F811
    db,
    session_factory,  # noqa: F811
):
    _, create, _, _ = setup_flow
    lot = await create()
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    job = review_jobs.enqueue(row)
    job = {
        **job,
        "status": "running",
        "lease_until": (datetime.now(UTC) - timedelta(seconds=5)).isoformat(),
    }
    row.data = {**row.data, "review_job": job, "_review_cache": {"candidates": {"saved": {}}}}
    await db.commit()
    assert await review_jobs.claim(session_factory) is None
    await db.refresh(row)
    assert row.data["review_job"]["status"] == "interrupted"
    assert "saved" in row.data["_review_cache"]["candidates"]


async def test_old_job_cannot_publish_after_lot_revision_changes(
    setup_flow,  # noqa: F811
    db,
    session_factory,  # noqa: F811
):
    _, create, _, _ = setup_flow
    lot = await create()
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    job = deepcopy(review_jobs.enqueue(row))
    row.revision += 1
    await db.commit()
    with pytest.raises(review_jobs.ObsoleteReview):
        await review_jobs.update(session_factory, row.id, job["id"], phase="saving")


async def test_worker_runs_real_workflow_and_saves_selected_sites(
    setup_flow,  # noqa: F811
    session_factory,
    monkeypatch,  # noqa: F811
):
    from types import SimpleNamespace

    from app.domains.diagnosis.client import EngineResponse
    from app.domains.treatment import progressive
    from app.domains.treatment.intake import IntakeBatchResult, IntakeResult, LotReview

    req, create, _, _ = setup_flow
    lot = await create()
    await req("A", f"/lots/{lot['id']}/review-jobs", {"revision": lot["revision"]})

    async def engine_request(*args, **kwargs):
        return EngineResponse(200, detail())

    async def nearby(packets, result, origin, settings, context, cache, report, **kwargs):
        keys = [p["capability_key"] for p in packets[:5]]
        for option in result.options:
            option.facilities = [f for f in option.facilities if f.capability_key in keys]
        result.options = [o for o in result.options if o.facilities]
        await report(
            "facility_review",
            completed=5,
            total=len(packets),
            selected=5,
            cache={"candidates": {"persisted": {}}},
        )
        return (
            IntakeBatchResult(
                results={
                    key: IntakeResult(
                        status="reviewed",
                        finding="form_mentioned",
                        next_check="반입 규격 확인",
                        lot_review=LotReview(status="reviewed", observation_method="no_photo"),
                    )
                    for key in keys
                }
            ),
            {"policy": "road-top-five-v1", "selected_keys": keys},
            {"candidates": {"persisted": {}}},
        )

    monkeypatch.setattr(progressive, "review_nearby", nearby)
    assert await review_jobs.run_next(
        session_factory, engine=SimpleNamespace(request=engine_request)
    )
    finished = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    assert finished["review_progress"]["status"] == "completed", finished["review_progress"]
    assert len(finished["review"]["selection"]["selected_keys"]) == 5
    assert finished["revision"] == lot["revision"]


async def test_pending_conditional_and_accepted_handoffs_are_planned_before_dispatch():
    from types import SimpleNamespace

    from app.domains.transport.road_route import handoff_legs

    origin = {"latitude": 37.17, "longitude": 126.84}
    destination = {"latitude": 37.14, "longitude": 126.81}
    lot = SimpleNamespace(data={"initial": {"origin": origin}})
    for status in ["pending", "conditional", "accepted"]:
        offer = SimpleNamespace(
            id="ab", status=status, data={"facility": {"location": destination}}
        )
        assert handoff_legs(lot, [offer]) == [("ab", (126.84, 37.17), (126.81, 37.14))]
    for status in ["rejected", "cancelled"]:
        offer.status = status
        assert handoff_legs(lot, [offer]) == []
