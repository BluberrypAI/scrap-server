"""docs/specs/review-intake.md 완료 조건."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reviews.models import Review
from app.domains.users.models import User
from app.domains.users.service import purge_withdrawn_users

REVIEWS = "/api/v1/reviews"
TEXT = "사출 공정에서 나온 PP 파쇄품이 월 3톤 정도 나옵니다. 재활용 업체를 찾고 싶어요."


async def create(client: AsyncClient, **extra) -> dict:
    res = await client.post(REVIEWS, json={"free_text": TEXT, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def intake_of(client: AsyncClient, review_id: str) -> dict:
    res = await client.get(f"{REVIEWS}/{review_id}/intake")
    assert res.status_code == 200
    return res.json()


async def answer(client: AsyncClient, review_id: str, *answers: dict):
    return await client.patch(f"{REVIEWS}/{review_id}/intake", json={"answers": list(answers)})


def fields(items: list[dict]) -> dict:
    return {i["field"]: i for i in items}


# --- 생성 ---


async def test_create_without_company_returns_409(auth_client: AsyncClient):
    res = await auth_client.post(REVIEWS, json={"free_text": TEXT})

    assert res.status_code == 409
    assert res.json()["code"] == "COMPANY_REQUIRED"


async def test_create_returns_201_pending_with_company_version(company_client: AsyncClient):
    body = await create(company_client)

    assert body["status"] == "intake_pending"
    assert body["company_profile_version"] == 1


@pytest.mark.parametrize(
    ("free_text", "code"), [("   ", "EMPTY_INPUT"), ("가" * 5001, "TEXT_TOO_LONG")]
)
async def test_create_rejects_empty_or_long_text(company_client: AsyncClient, free_text, code):
    res = await company_client.post(REVIEWS, json={"free_text": free_text})

    assert res.status_code == 422
    assert res.json()["code"] == code


async def test_company_defaults_stay_unconfirmed(company_client: AsyncClient):
    review = await create(company_client)

    body = await intake_of(company_client, review["review_id"])

    assert body["intake"]["confirmed"] == []
    unconfirmed = fields(body["intake"]["unconfirmed"])
    assert unconfirmed["material"] == {
        "field": "material",
        "value": "PP",
        "source": "company_profile",
    }
    assert unconfirmed["generation_process"]["value"] == "플라스틱 사출 성형"
    questions = fields(body["questions"])
    assert questions["material"]["required"] is True
    assert questions["quantity_kg"]["required"] is True


async def test_overrides_are_confirmed_and_make_review_ready(company_client: AsyncClient):
    review = await create(company_client, overrides={"material": "PP", "quantity_kg": 3000})

    assert review["status"] == "intake_ready"
    body = await intake_of(company_client, review["review_id"])
    confirmed = fields(body["intake"]["confirmed"])
    assert confirmed["material"]["source"] == "user"
    assert confirmed["quantity_kg"]["value"] == 3000
    assert not any(q["required"] for q in body["questions"])


async def test_title_defaults_to_first_30_chars(company_client: AsyncClient):
    review = await create(company_client)

    res = await company_client.get(f"{REVIEWS}/{review['review_id']}")

    assert res.json()["title"] == TEXT[:30]
    assert res.json()["free_text"] == TEXT
    assert res.json()["intake_version"] == 1


# --- 보완 질문 답변 ---


async def test_answers_confirm_values_and_bump_version(company_client: AsyncClient):
    review_id = (await create(company_client))["review_id"]

    res = await answer(
        company_client,
        review_id,
        {"field": "material", "value": "PP"},
        {"field": "quantity_kg", "value": 3, "unit": "t"},
    )

    assert res.status_code == 200
    assert res.json() == {"status": "intake_ready", "intake_version": 2}
    confirmed = fields((await intake_of(company_client, review_id))["intake"]["confirmed"])
    assert confirmed["quantity_kg"]["value"] == 3000


async def test_same_answer_does_not_bump_version(company_client: AsyncClient):
    review_id = (await create(company_client, overrides={"region": "경기"}))["review_id"]

    res = await answer(company_client, review_id, {"field": "region", "value": "경기"})

    assert res.json()["intake_version"] == 1


async def test_null_answer_is_recorded_as_unknown(company_client: AsyncClient):
    review_id = (await create(company_client))["review_id"]

    await answer(company_client, review_id, {"field": "region", "value": None})

    body = await intake_of(company_client, review_id)
    assert fields(body["intake"]["confirmed"])["region"]["value"] is None
    assert "region" not in fields(body["questions"])


async def test_unknown_required_value_keeps_review_pending(company_client: AsyncClient):
    review_id = (await create(company_client))["review_id"]

    res = await answer(
        company_client,
        review_id,
        {"field": "material", "value": "PP"},
        {"field": "quantity_kg", "value": None},
    )

    assert res.json()["status"] == "intake_pending"


async def test_no_test_report_asks_measured_values(company_client: AsyncClient):
    review_id = (await create(company_client))["review_id"]

    await answer(company_client, review_id, {"field": "has_test_report", "value": False})

    questions = fields((await intake_of(company_client, review_id))["questions"])
    assert {"moisture_pct", "contamination_pct"} <= set(questions)
    assert "documents" not in questions


async def test_test_report_asks_document_upload(company_client: AsyncClient):
    review_id = (await create(company_client))["review_id"]

    await answer(company_client, review_id, {"field": "has_test_report", "value": True})

    questions = fields((await intake_of(company_client, review_id))["questions"])
    assert "documents" in questions
    assert "moisture_pct" not in questions


async def test_contradicting_contamination_blocks_run(company_client: AsyncClient):
    review = await create(
        company_client,
        overrides={
            "material": "PP",
            "quantity_kg": 3000,
            "contamination": "라벨 이물 혼입",
            "contamination_pct": 0,
        },
    )

    assert review["status"] == "intake_pending"
    question = fields((await intake_of(company_client, review["review_id"]))["questions"])
    assert question["contamination_pct"]["required"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {"field": "unknown", "value": 1},
        {"field": "quantity_kg", "value": -1},
        {"field": "quantity_kg", "value": 1, "unit": "lb"},
        {"field": "color", "value": "흰색", "unit": "kg"},
        {"field": "designated_waste", "value": "yes"},
        {"field": "moisture_pct", "value": 101},
    ],
)
async def test_invalid_answer_returns_422(company_client: AsyncClient, bad):
    review_id = (await create(company_client))["review_id"]

    res = await answer(company_client, review_id, bad)

    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"


async def test_duplicate_answer_fields_return_422(company_client: AsyncClient):
    review_id = (await create(company_client))["review_id"]

    res = await answer(
        company_client,
        review_id,
        {"field": "region", "value": "경기"},
        {"field": "region", "value": "서울"},
    )

    assert res.status_code == 422


# --- 목록·접근 격리 ---


async def test_list_returns_my_reviews_newest_first(company_client: AsyncClient):
    first = await create(company_client, title="첫 검토")
    second = await create(company_client, title="둘째 검토")

    res = await company_client.get(REVIEWS, params={"pageSize": 1})

    body = res.json()
    assert [i["review_id"] for i in body["items"]] == [second["review_id"]]
    assert body["pagingInfo"]["elementCount"] == 2
    assert body["pagingInfo"]["totalPageCount"] == 2
    asc = await company_client.get(REVIEWS, params={"sort": "created_at,asc"})
    assert asc.json()["items"][0]["review_id"] == first["review_id"]


async def test_invalid_sort_returns_422(company_client: AsyncClient):
    res = await company_client.get(REVIEWS, params={"sort": "title"})

    assert res.status_code == 422


async def test_other_company_cannot_see_review(
    company_client: AsyncClient, other_client: AsyncClient
):
    review_id = (await create(company_client))["review_id"]

    for path in (f"{REVIEWS}/{review_id}", f"{REVIEWS}/{review_id}/intake"):
        res = await other_client.get(path)
        assert res.status_code == 404
    patch = await answer(other_client, review_id, {"field": "region", "value": "서울"})
    assert patch.status_code == 404
    listed = await other_client.get(REVIEWS)
    assert listed.json()["items"] == []


async def test_purge_deletes_reviews(company_client: AsyncClient, db: AsyncSession, user: User):
    await create(company_client)
    user.withdrawn_at = datetime.now(UTC) - timedelta(days=31)
    user.deletion_scheduled_at = datetime.now(UTC) - timedelta(days=1)
    db.add(user)
    await db.commit()

    await purge_withdrawn_users(db)

    assert await db.scalar(select(func.count()).select_from(Review)) == 0
