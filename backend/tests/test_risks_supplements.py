"""docs/specs/review-risks-supplements.md 완료 조건.

엔진 응답 예시(tests/engine_fixtures.py): plan-a 1단계에 보통 리스크 2개,
plan-b 1단계에 심각 리스크(plan-b-r1)와 보통 리스크(plan-b-r2). 두 후보 모두 2단계까지 있음.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.models import DocumentValue, VerificationStatus
from app.domains.risks.models import RiskEvidence, RiskStepDecision
from app.domains.supplements.models import Supplement
from app.domains.users.models import User
from app.domains.users.service import purge_withdrawn_users
from tests.engine_fixtures import FakeEngine

pytestmark = pytest.mark.usefixtures("run_queue")


@pytest.fixture
async def run_id(company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine) -> str:
    res = await company_client.post(
        f"/api/v1/reviews/{ready_review}/runs", json={"intake_version": 1}
    )
    return res.json()["run_id"]


def run_url(review_id: str, run_id: str) -> str:
    return f"/api/v1/reviews/{review_id}/runs/{run_id}"


async def decide(client, review_id, run_id, candidate, step, decision, option=None):
    return await client.post(
        f"{run_url(review_id, run_id)}/candidates/{candidate}/risk-steps/{step}/decision",
        json={"decision": decision, "proceed_option": option},
    )


async def add_supplement(client: AsyncClient, review_id: str, **form) -> dict:
    data = {
        "type": "inspection_result",
        "effective_date": "2026-10-01",
        "applied_quantity_value": "3",
        "applied_quantity_unit": "t",
        "verification_status": "verified",
        **form,
    }
    res = await client.post(f"/api/v1/reviews/{review_id}/supplements", data=data)
    return res


async def link(client, review_id, run_id, risk_id, **body):
    return await client.post(f"{run_url(review_id, run_id)}/risks/{risk_id}/evidence", json=body)


async def detail(client, review_id, run_id, candidate) -> dict:
    res = await client.get(f"{run_url(review_id, run_id)}/candidates/{candidate}")
    return res.json()


# --- 단계 결정 ---


async def test_confirm_moves_to_next_step_but_does_not_resolve(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await decide(company_client, ready_review, run_id, "plan-a", 1, "confirm")

    assert res.status_code == 200
    assert res.json()["next_step"] == 2
    body = await detail(company_client, ready_review, run_id, "plan-a")
    assert body["risk_steps"]["current_step"] == 2
    assert body["risk_steps"]["steps"][0]["decision"] == "confirm"
    assert {r["status"] for r in body["risks"]} == {"confirmed"}


async def test_deciding_later_step_first_returns_409(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await decide(company_client, ready_review, run_id, "plan-a", 2, "confirm")

    assert res.status_code == 409
    assert res.json()["code"] == "STEP_OUT_OF_ORDER"


async def test_redeciding_finished_step_returns_409(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    await decide(company_client, ready_review, run_id, "plan-a", 1, "hold")

    res = await decide(company_client, ready_review, run_id, "plan-a", 1, "confirm")

    assert res.status_code == 409


async def test_request_evidence_keeps_current_step(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    first = await decide(company_client, ready_review, run_id, "plan-a", 1, "request_evidence")
    assert first.json()["next_step"] == 1

    res = await decide(company_client, ready_review, run_id, "plan-a", 1, "confirm")

    assert res.status_code == 200
    assert res.json()["next_step"] == 2


async def test_severe_risk_requires_proceed_option(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await decide(company_client, ready_review, run_id, "plan-b", 1, "confirm")

    assert res.status_code == 409
    assert res.json()["code"] == "RISK_OPTION_REQUIRED"
    ok = await decide(company_client, ready_review, run_id, "plan-b", 1, "confirm", "exclude")
    assert ok.status_code == 200
    assert ok.json()["proceed_option"] == "exclude"


async def test_last_step_decision_finishes_candidate(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    await decide(company_client, ready_review, run_id, "plan-a", 1, "confirm")

    res = await decide(company_client, ready_review, run_id, "plan-a", 2, "hold")

    assert res.json()["next_step"] is None


@pytest.mark.parametrize(("candidate", "step"), [("plan-a", 3), ("plan-a", 0), ("nope", 1)])
async def test_unknown_step_or_candidate_returns_404(
    company_client: AsyncClient, ready_review: str, run_id: str, candidate, step
):
    res = await decide(company_client, ready_review, run_id, candidate, step, "confirm")

    assert res.status_code == 404


# --- 추가 자료 ---


async def test_supplement_without_quantity_returns_422(
    company_client: AsyncClient, ready_review: str
):
    res = await add_supplement(company_client, ready_review, applied_quantity_value="")

    assert res.status_code == 422
    assert res.json()["code"] == "MISSING_QUANTITY"


async def test_matching_quantity_in_tonnes_is_matched(
    company_client: AsyncClient, ready_review: str
):
    res = await add_supplement(company_client, ready_review)

    assert res.status_code == 201
    assert res.json()["applicability"] == "matched"
    assert res.json()["counted_in_judgment"] is True


async def test_different_quantity_is_mismatch(company_client: AsyncClient, ready_review: str):
    res = await add_supplement(
        company_client, ready_review, applied_quantity_value="2000", applied_quantity_unit="kg"
    )

    assert res.json()["applicability"] == "mismatch"
    assert "3000" in res.json()["mismatch_reason"]
    assert res.json()["counted_in_judgment"] is False


async def test_unverified_supplement_is_not_counted(company_client: AsyncClient, ready_review: str):
    res = await add_supplement(company_client, ready_review, verification_status="unverified")

    assert res.json()["applicability"] == "matched"
    assert res.json()["counted_in_judgment"] is False


async def test_supplement_with_file_and_list(company_client: AsyncClient, ready_review: str):
    await company_client.post(
        f"/api/v1/reviews/{ready_review}/supplements",
        data={
            "type": "quote",
            "effective_date": "2026-10-02",
            "applied_quantity_value": "3000",
            "value": "120000",
        },
        files={"file": ("견적서.pdf", b"%PDF quote", "application/pdf")},
    )

    res = await company_client.get(f"/api/v1/reviews/{ready_review}/supplements")

    item = res.json()["items"][0]
    assert item["type"] == "quote"
    assert item["file_name"] == "견적서.pdf"
    assert item["value"] == 120000
    assert item["applied_quantity_kg"] == 3000
    assert item["verification_status"] == "unverified"


async def test_supplement_rejects_unknown_unit(company_client: AsyncClient, ready_review: str):
    res = await add_supplement(company_client, ready_review, applied_quantity_unit="lb")

    assert res.status_code == 422


# --- 증빙 연결 ---


async def test_linking_matched_supplement_resolves_risk(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    supplement_id = (await add_supplement(company_client, ready_review)).json()["supplement_id"]

    res = await link(company_client, ready_review, run_id, "plan-b-r1", supplement_id=supplement_id)

    assert res.status_code == 200
    assert res.json() == {"risk_id": "plan-b-r1", "status": "resolved"}
    risks = {
        r["risk_id"]: r["status"]
        for r in (await detail(company_client, ready_review, run_id, "plan-b"))["risks"]
    }
    assert risks == {"plan-b-r1": "resolved", "plan-b-r2": "open"}
    tasks = await company_client.get(
        f"{run_url(ready_review, run_id)}/tasks", params={"status": "done"}
    )
    assert [t["risk_id"] for t in tasks.json()["items"]] == ["plan-b-r1"]


async def test_resolved_severe_risk_no_longer_needs_option(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    supplement_id = (await add_supplement(company_client, ready_review)).json()["supplement_id"]
    await link(company_client, ready_review, run_id, "plan-b-r1", supplement_id=supplement_id)

    res = await decide(company_client, ready_review, run_id, "plan-b", 1, "confirm")

    assert res.status_code == 200


@pytest.mark.parametrize(
    "form", [{"verification_status": "unverified"}, {"applied_quantity_value": "1"}]
)
async def test_unusable_supplement_returns_422(
    company_client: AsyncClient, ready_review: str, run_id: str, form
):
    supplement_id = (await add_supplement(company_client, ready_review, **form)).json()[
        "supplement_id"
    ]

    res = await link(company_client, ready_review, run_id, "plan-b-r1", supplement_id=supplement_id)

    assert res.status_code == 422
    assert res.json()["code"] == "EVIDENCE_NOT_APPLICABLE"


async def test_document_needs_verified_value_to_resolve(
    company_client: AsyncClient, ready_review: str, run_id: str, db: AsyncSession
):
    upload = await company_client.post(
        f"/api/v1/reviews/{ready_review}/documents",
        files={"file": ("r.pdf", b"%PDF", "application/pdf")},
    )
    document_id = upload.json()["document_id"]

    before = await link(company_client, ready_review, run_id, "plan-a-r1", document_id=document_id)
    assert before.status_code == 422

    db.add(
        DocumentValue(
            document_id=uuid.UUID(document_id),
            name="함수율",
            value=8.0,
            unit="%",
            verification_status=VerificationStatus.VERIFIED,
        )
    )
    await db.commit()
    after = await link(company_client, ready_review, run_id, "plan-a-r1", document_id=document_id)
    assert after.status_code == 200


async def test_evidence_needs_exactly_one_source(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await link(company_client, ready_review, run_id, "plan-a-r1")

    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"


async def test_unknown_risk_returns_404(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    supplement_id = (await add_supplement(company_client, ready_review)).json()["supplement_id"]

    res = await link(company_client, ready_review, run_id, "nope", supplement_id=supplement_id)

    assert res.status_code == 404


# --- 재실행 ---


async def test_rerun_creates_child_run_with_supplements(
    company_client: AsyncClient, ready_review: str, run_id: str, fake_engine: FakeEngine
):
    supplement_id = (await add_supplement(company_client, ready_review)).json()["supplement_id"]

    res = await company_client.post(
        f"{run_url(ready_review, run_id)}/rerun", json={"supplement_ids": [supplement_id]}
    )

    assert res.status_code == 202
    body = res.json()
    assert body["rerun_from_stage"] == "research"
    assert body["reused_stages"] == ["intake"]
    child = (await company_client.get(run_url(ready_review, body["new_run_id"]))).json()
    assert child["parent_run_id"] == run_id
    assert child["pinned_versions"]["supplement_ids"] == [supplement_id]
    assert child["status"] == "completed"
    assert len(fake_engine.lots) == 2


async def test_rerun_with_mismatched_supplement_returns_409(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    supplement_id = (
        await add_supplement(company_client, ready_review, applied_quantity_value="1")
    ).json()["supplement_id"]

    res = await company_client.post(
        f"{run_url(ready_review, run_id)}/rerun", json={"supplement_ids": [supplement_id]}
    )

    assert res.status_code == 409
    assert res.json()["code"] == "NO_APPLICABLE_SUPPLEMENT"


async def test_rerun_with_unknown_supplement_returns_404(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.post(
        f"{run_url(ready_review, run_id)}/rerun", json={"supplement_ids": [str(uuid.uuid4())]}
    )

    assert res.status_code == 404


# --- 접근 격리·삭제 ---


async def test_other_company_cannot_touch_risks_or_supplements(
    company_client: AsyncClient, other_client: AsyncClient, ready_review: str, run_id: str
):
    assert (
        await decide(other_client, ready_review, run_id, "plan-a", 1, "confirm")
    ).status_code == 404
    assert (await add_supplement(other_client, ready_review)).status_code == 404
    listed = await other_client.get(f"/api/v1/reviews/{ready_review}/supplements")
    assert listed.status_code == 404


async def test_purge_deletes_supplements_decisions_and_evidence(
    company_client: AsyncClient, ready_review: str, run_id: str, db: AsyncSession, user: User
):
    supplement_id = (await add_supplement(company_client, ready_review)).json()["supplement_id"]
    await link(company_client, ready_review, run_id, "plan-b-r1", supplement_id=supplement_id)
    await decide(company_client, ready_review, run_id, "plan-a", 1, "confirm")
    user.withdrawn_at = datetime.now(UTC) - timedelta(days=31)
    user.deletion_scheduled_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    await purge_withdrawn_users(db)

    for model in (Supplement, RiskEvidence, RiskStepDecision):
        assert await db.scalar(select(func.count()).select_from(model)) == 0
