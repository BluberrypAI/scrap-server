"""docs/specs/review-runs.md 완료 조건."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.models import DocumentValue, VerificationStatus
from app.domains.runs import service as run_service
from app.domains.runs.engine_client import get_engine_client
from app.domains.runs.models import Run, RunStatus
from app.domains.users.models import User
from app.domains.users.service import purge_withdrawn_users
from app.main import app
from tests.engine_fixtures import FakeEngine, InlineQueue, research_result

pytestmark = pytest.mark.usefixtures("run_queue")


def runs_url(review_id: str) -> str:
    return f"/api/v1/reviews/{review_id}/runs"


async def start(client: AsyncClient, review_id: str, **body):
    return await client.post(runs_url(review_id), json={"intake_version": 1, **body})


async def read(client: AsyncClient, review_id: str, run_id: str) -> dict:
    res = await client.get(f"{runs_url(review_id)}/{run_id}")
    assert res.status_code == 200
    return res.json()


def stage_map(run: dict) -> dict:
    return {s["stage"]: s for s in run["stages"]}


# --- 실행 생성 ---


async def test_start_returns_202_queued_with_pinned_versions(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    res = await start(company_client, ready_review)

    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "queued"
    pinned = body["pinned_versions"]
    assert pinned["intake_version"] == 1
    assert pinned["company_profile_version"] == 1
    assert pinned["evidence_grade"] == "C"
    assert pinned["graph_trace"] is None


async def test_completed_run_pins_graph_and_router_state(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    run_id = (await start(company_client, ready_review)).json()["run_id"]

    run = await read(company_client, ready_review, run_id)

    assert run["status"] == "completed"
    assert run["router_state"] == "REVIEW"
    assert run["pinned_versions"]["graph_trace"] == {
        "graph_generation": "gen-1",
        "reference_sha256": "ref-1",
    }
    assert run["pinned_versions"]["engine_contract_version"] == "candidate-research-v1"
    stages = stage_map(run)
    assert stages["research"]["status"] == "done"
    assert stages["cost_carbon"]["status"] == "skipped"
    assert stages["critic"]["status"] == "skipped"
    assert stages["router"]["status"] == "done"
    assert run["limitations"] == ["법령은 검색 후보입니다."]
    assert run["error"] is None


async def test_lot_contains_only_confirmed_engine_fields(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    await start(company_client, ready_review)

    # 업종 기본값(generation_process)은 미확인이라 빠지고, has_test_report는 server 전용이라 빠짐
    assert fake_engine.lots == [{"material": "PP", "quantity_kg": 3000}]


async def test_engine_not_configured_returns_503(company_client: AsyncClient, ready_review: str):
    app.dependency_overrides[get_engine_client] = lambda: None

    res = await start(company_client, ready_review)

    assert res.status_code == 503
    assert res.json()["code"] == "ENGINE_UNAVAILABLE"


async def test_pending_intake_returns_409(company_client: AsyncClient, fake_engine: FakeEngine):
    review = await company_client.post("/api/v1/reviews", json={"free_text": "PP"})

    res = await start(company_client, review.json()["review_id"])

    assert res.status_code == 409
    assert res.json()["code"] == "INTAKE_INCOMPLETE"


async def test_stale_intake_version_returns_409(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    await company_client.patch(
        f"/api/v1/reviews/{ready_review}/intake",
        json={"answers": [{"field": "region", "value": "경기"}]},
    )

    res = await start(company_client, ready_review)

    assert res.status_code == 409
    assert res.json()["code"] == "VERSION_CONFLICT"


async def test_second_run_while_queued_returns_409(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine, run_queue: InlineQueue
):
    run_queue.enabled = False
    await start(company_client, ready_review)

    res = await start(company_client, ready_review)

    assert res.status_code == 409
    assert res.json()["code"] == "RUN_IN_PROGRESS"


# --- 엔진 실패 ---


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(503, json={"detail": {"code": "neo4j-unavailable"}}), "ENGINE_UNAVAILABLE"),
        (httpx.Response(409, json={"detail": {"code": "stale-cursor"}}), "GRAPH_VERSION_CHANGED"),
        (httpx.Response(422, json={"detail": []}), "ENGINE_REJECTED_INPUT"),
        (httpx.Response(200, json={"contract_version": "other"}), "ENGINE_CONTRACT_MISMATCH"),
    ],
)
async def test_engine_errors_fail_the_run(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine, response, code
):
    fake_engine.respond = lambda: response
    run_id = (await start(company_client, ready_review)).json()["run_id"]

    run = await read(company_client, ready_review, run_id)

    assert run["status"] == "failed"
    assert run["error"]["code"] == code
    assert stage_map(run)["research"]["status"] == "failed"
    assert run["finished_at"] is not None


async def test_engine_connection_error_fails_the_run(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    def refuse():
        raise httpx.ConnectError("refused")

    fake_engine.respond = refuse
    run_id = (await start(company_client, ready_review)).json()["run_id"]

    run = await read(company_client, ready_review, run_id)

    assert run["error"]["code"] == "ENGINE_UNAVAILABLE"


async def test_failed_run_allows_new_run(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    fake_engine.respond = lambda: httpx.Response(503)
    await start(company_client, ready_review)
    fake_engine.respond = lambda: httpx.Response(200, json=research_result())

    res = await start(company_client, ready_review)

    assert res.status_code == 202


async def test_incomplete_coverage_marks_run_partial(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    fake_engine.respond = lambda: httpx.Response(
        200, json=research_result(coverage={"all_pages_read": False})
    )
    run_id = (await start(company_client, ready_review)).json()["run_id"]

    run = await read(company_client, ready_review, run_id)

    assert run["status"] == "partial"
    assert stage_map(run)["research"]["status"] == "limit_reached"


# --- 근거 문서 ---


async def upload_report(client: AsyncClient, review_id: str, doc_type: str) -> str:
    res = await client.post(
        f"/api/v1/reviews/{review_id}/documents",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        data={"doc_type": doc_type},
    )
    return res.json()["document_id"]


async def test_verified_test_report_value_gives_grade_a(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine, db: AsyncSession
):
    document_id = await upload_report(company_client, ready_review, "test_report")
    value = DocumentValue(
        document_id=uuid.UUID(document_id),
        name="함수율",
        value=12.0,
        unit="%",
        verification_status=VerificationStatus.VERIFIED,
    )
    db.add(value)
    await db.commit()

    res = await start(company_client, ready_review, document_ids=[document_id])

    pinned = res.json()["pinned_versions"]
    assert pinned["evidence_grade"] == "A"
    assert pinned["verified_value_ids"] == [str(value.id)]


async def test_user_confirmed_measurement_gives_grade_b(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    await company_client.patch(
        f"/api/v1/reviews/{ready_review}/intake",
        json={"answers": [{"field": "moisture_pct", "value": 8, "unit": "%"}]},
    )

    res = await start(company_client, ready_review, intake_version=2)

    assert res.json()["pinned_versions"]["evidence_grade"] == "B"


async def test_document_of_other_review_returns_422(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    other = await company_client.post("/api/v1/reviews", json={"free_text": "다른 검토"})
    document_id = await upload_report(company_client, other.json()["review_id"], "other")

    res = await start(company_client, ready_review, document_ids=[document_id])

    assert res.status_code == 422


# --- 조회 ---


async def test_list_runs_newest_first_and_latest_run_on_review(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    first = (await start(company_client, ready_review)).json()["run_id"]
    second = (await start(company_client, ready_review)).json()["run_id"]

    res = await company_client.get(runs_url(ready_review))

    assert [r["run_id"] for r in res.json()["items"]] == [second, first]
    review = await company_client.get(f"/api/v1/reviews/{ready_review}")
    assert review.json()["latest_run_id"] == second
    listed = await company_client.get("/api/v1/reviews")
    assert listed.json()["items"][0]["latest_run_id"] == second


async def test_other_company_cannot_see_runs(
    company_client: AsyncClient,
    other_client: AsyncClient,
    ready_review: str,
    fake_engine: FakeEngine,
):
    run_id = (await start(company_client, ready_review)).json()["run_id"]

    assert (await other_client.get(f"{runs_url(ready_review)}/{run_id}")).status_code == 404
    assert (await other_client.get(runs_url(ready_review))).status_code == 404
    assert (await start(other_client, ready_review)).status_code == 404


async def test_unknown_run_returns_404(company_client: AsyncClient, ready_review: str):
    res = await company_client.get(f"{runs_url(ready_review)}/{uuid.uuid4()}")

    assert res.status_code == 404


# --- 복구·삭제 ---


async def test_recover_marks_unfinished_runs_failed(
    company_client: AsyncClient,
    ready_review: str,
    fake_engine: FakeEngine,
    run_queue: InlineQueue,
    db: AsyncSession,
):
    run_queue.enabled = False
    run_id = (await start(company_client, ready_review)).json()["run_id"]

    assert await run_service.recover_interrupted(db) == 1

    run = await read(company_client, ready_review, run_id)
    assert run["status"] == "failed"
    assert run["error"]["code"] == "WORKER_INTERRUPTED"


async def test_purge_deletes_runs(
    company_client: AsyncClient,
    ready_review: str,
    fake_engine: FakeEngine,
    db: AsyncSession,
    user: User,
):
    await start(company_client, ready_review)
    user.withdrawn_at = datetime.now(UTC) - timedelta(days=31)
    user.deletion_scheduled_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    await purge_withdrawn_users(db)

    assert await db.scalar(select(func.count()).select_from(Run)) == 0


async def test_run_status_values_are_stable():
    # 프론트엔드가 쓰는 값이라 바꾸면 안 됨
    assert [s.value for s in RunStatus] == ["queued", "running", "completed", "partial", "failed"]
