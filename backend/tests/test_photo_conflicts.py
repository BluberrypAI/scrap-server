import io
import uuid
from copy import deepcopy

import pytest
from PIL import Image

from app.domains.transport.models import WorkflowLot
from app.domains.transport.photo_conflicts import conflict_gate
from tests.test_pp_company_workflow import setup_flow as _setup_flow
from tests.test_vendor_inquiry import reviewed

setup_flow = _setup_flow
NOTE = "합성 테스트: 사진의 여러 색 조각을 확인했으며 문진의 재질·발생 공정은 같습니다."


async def conflicted(req, create, db):
    lot = await reviewed(req, await create())
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    review = deepcopy(row.review)
    # One candidate's conflict must also block a different candidate's offer.
    item = next(iter(review["results"].values()))
    item["lot_review"]["concerns"] = [
        {
            "category": "description_conflict",
            "basis": "description",
            "reference": "합성 테스트 PP",
            "concern": "흰색만이라는 설명과 여러 색 관찰이 다릅니다.",
            "next_check": "설명을 확인해 주세요.",
        }
    ]
    row.review = review
    await db.commit()
    lot = (await req("A", f"/lots/{lot['id']}", method="GET")).json()
    key = next(
        f["capability_key"]
        for o in lot["review"]["next_step"]["options"]
        for f in o["facilities"]
        if f["facility_key"] == "sarom-hwaseong-2"
    )
    return lot, key


async def resolve(req, lot, **body):
    return await req(
        "A",
        f"/lots/{lot['id']}/photo-conflict-resolution",
        {"revision": lot["revision"], "note": NOTE, **body},
    )


async def test_conflict_blocks_offer_and_confirmation_is_shared_without_reclassification(
    setup_flow, db
):
    req, create, _, _ = setup_flow
    lot, key = await conflicted(req, create, db)
    assert lot["photo_conflict_gate"]["blocked"]
    path = f"/lots/{lot['id']}/offers"
    assert (
        await req("A", path, {"revision": lot["revision"], "capability_key": key})
    ).status_code == 409
    assert (await resolve(req, lot, action="confirm")).status_code == 422
    assert (
        await resolve(req, lot, action="confirm", classification_unchanged=True, note=" ")
    ).status_code == 422
    saved = await resolve(req, lot, action="confirm", classification_unchanged=True)
    assert saved.status_code == 200, saved.text
    checked = saved.json()
    assert not checked["photo_conflict_gate"]["blocked"]
    for field in ("initial", "handoff", "recycling", "current"):
        assert checked["data"].get(field) == lot["data"].get(field)
    assert checked["review"] == lot["review"]
    sent = await req("A", path, {"revision": checked["revision"], "capability_key": key})
    assert sent.status_code == 200, sent.text
    recipient = (await req("B", f"/lots/{lot['id']}", method="GET")).json()
    snapshot = recipient["offers"][-1]["data"]["photo_conflict_resolution"]
    assert snapshot["note"] == NOTE and snapshot["issues"]
    assert (
        await resolve(req, sent.json(), action="correct", condition="여러 색 조각입니다")
    ).status_code == 409


async def test_correction_requires_new_review_and_preserves_classification(setup_flow, db):
    req, create, _, _ = setup_flow
    lot, key = await conflicted(req, create, db)
    same = await resolve(req, lot, action="correct", condition=lot["data"]["current"]["condition"])
    assert same.status_code == 422
    response = await resolve(
        req, lot, action="correct", condition="사진에는 여러 색의 조각이 있습니다. 합성 테스트"
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["review"] is None
    for field in ("handoff", "recycling", "initial"):
        assert edited["data"].get(field) == lot["data"].get(field)
    assert (
        await req(
            "A",
            f"/lots/{lot['id']}/offers",
            {"revision": edited["revision"], "capability_key": key},
        )
    ).status_code == 409
    fresh = await reviewed(req, edited)
    assert not fresh["photo_conflict_gate"]["blocked"]
    assert fresh["photo_conflict_gate"]["resolution"] is None


@pytest.mark.parametrize("change", ["review", "current", "stage", "company", "photo"])
async def test_previous_confirmation_never_covers_changed_context(setup_flow, db, change):
    req, create, _, _ = setup_flow
    lot, _ = await conflicted(req, create, db)
    lot = (await resolve(req, lot, action="confirm", classification_unchanged=True)).json()
    if change == "photo":
        stream = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(stream, format="PNG")
        res = await req(
            "A",
            f"/lots/{lot['id']}/photos",
            files={"file": ("test.png", stream.getvalue(), "image/png")},
        )
        assert res.status_code == 200, res.text
        assert (
            res.json()["review"] is None and res.json()["photo_conflict_gate"]["resolution"] is None
        )
        return
    row = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    if change == "review":
        row.review = {**row.review, "at": "another-review"}
    elif change == "company":
        row.current_company_id = uuid.uuid4()
    else:
        data = deepcopy(row.data)
        if change == "stage":
            data["completed"].append({})
        else:
            data["current"]["condition"] = "바뀐 설명"
        row.data = data
    assert conflict_gate(row)["blocked"]


async def test_other_company_stale_revision_and_missing_review_denied(setup_flow, db):
    req, create, _, _ = setup_flow
    fresh = await create()
    assert (
        await resolve(req, fresh, action="confirm", classification_unchanged=True)
    ).status_code == 409
    lot, _ = await conflicted(req, create, db)
    body = {
        "revision": lot["revision"],
        "action": "confirm",
        "note": NOTE,
        "classification_unchanged": True,
    }
    path = f"/lots/{lot['id']}/photo-conflict-resolution"
    assert (await req("B", path, body)).status_code in {403, 404}
    assert (await req("A", path, {**body, "revision": lot["revision"] + 1})).status_code == 409
