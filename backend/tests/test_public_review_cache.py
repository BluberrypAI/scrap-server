import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from app.domains.treatment import public_cache
from app.domains.treatment.intake import IntakeResult, LotReview
from app.domains.treatment.models import TreatmentSnapshot


async def test_store_persists_only_public_results_and_expires(session_factory):
    packet = {
        "capability_key": "site-a",
        "site": "공개 업체",
        "sources": [],
        "intake_answers": {"private": "PRIVATE-SENDER"},
    }
    store = public_cache.PublicReviewStore(session_factory)
    result = IntakeResult(status="needs_evidence", next_check="공개 투입 자료 없음")
    await store.put_many([packet], "model-v1", {"site-a": result})
    assert (await public_cache.PublicReviewStore(session_factory).get_many([packet], "model-v1"))[
        "site-a"
    ] == result
    assert await store.get_many([packet], "model-v2") == {}
    async with session_factory() as db:
        row = await db.get(TreatmentSnapshot, public_cache.KIND)
        assert "PRIVATE-SENDER" not in json.dumps(row.payload)
        values = deepcopy(row.payload)
        for value in values.values():
            value["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        row.payload = values
        await db.commit()
    assert await store.get_many([packet], "model-v1") == {}


async def test_model_failure_and_combined_lot_review_are_never_shared(session_factory):
    packet = {"capability_key": "site-a", "sources": []}
    store = public_cache.PublicReviewStore(session_factory)
    for result in [
        IntakeResult(status="model_unavailable", next_check="모델 미완료"),
        IntakeResult(
            status="reviewed",
            next_check="공개 사실",
            lot_review=LotReview(status="reviewed", questions=["PRIVATE-LOT"]),
        ),
    ]:
        await store.put_many([packet], "model-v1", {"site-a": result})
    assert await store.get_many([packet], "model-v1") == {}
    async with session_factory() as db:
        assert await db.get(TreatmentSnapshot, public_cache.KIND) is None


async def test_shared_store_is_bounded_and_keeps_newer_public_results(session_factory, monkeypatch):
    monkeypatch.setattr(public_cache, "LIMIT", 2)
    store = public_cache.PublicReviewStore(session_factory)
    packets = [{"capability_key": key, "sources": []} for key in ("a", "b", "c")]
    for packet in packets:
        await store.put_many(
            [packet],
            "model-v1",
            {
                packet["capability_key"]: IntakeResult(
                    status="needs_evidence", next_check="공개 자료 부족"
                )
            },
        )
    assert set(await store.get_many(packets, "model-v1")) == {"b", "c"}
