"""docs/specs/review-results.md 완료 조건."""

import httpx
import pytest
from httpx import AsyncClient

from tests.engine_fixtures import FakeEngine, InlineQueue, research_result

pytestmark = pytest.mark.usefixtures("run_queue")


async def run_review(client: AsyncClient, review_id: str) -> str:
    res = await client.post(f"/api/v1/reviews/{review_id}/runs", json={"intake_version": 1})
    assert res.status_code == 202
    return res.json()["run_id"]


def url(review_id: str, run_id: str, path: str) -> str:
    return f"/api/v1/reviews/{review_id}/runs/{run_id}/{path}"


@pytest.fixture
async def run_id(company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine) -> str:
    return await run_review(company_client, ready_review)


# --- 후보 목록 ---


async def test_candidates_keep_every_engine_candidate(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "candidates"))

    assert res.status_code == 200
    items = {i["candidate_id"]: i for i in res.json()["items"]}
    assert set(items) == {"plan-a", "plan-b"}
    assert items["plan-a"]["judgment"] == "needs_check"
    assert items["plan-b"]["judgment"] == "unsuitable"
    assert "시설 공개 조건과 맞지 않음" in [r["label"] for r in items["plan-b"]["judgment_reasons"]]


async def test_candidates_do_not_invent_rank_or_cost(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "candidates"))

    item = res.json()["items"][0]
    assert item["tentative_rank"] is None
    assert item["exclusion_reason"] is None
    assert item["cost_status"] == "missing"
    assert item["carbon_status"] == "missing"
    assert item["stale_company_profile"] is False


async def test_candidates_route_and_first_facility(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "candidates"))

    item = next(i for i in res.json()["items"] if i["candidate_id"] == "plan-a")
    assert [s["transition"] for s in item["process_route"]] == ["파쇄", "펠릿화"]
    assert item["process_route"][1]["facility"] is None
    assert item["process_route"][1]["condition_reason"] == "시설 연결 근거 없음"
    assert item["facility"]["name"] == "plan-a 파쇄 시설"
    assert item["risk_counts"] == {"high": 0, "medium": 2}


async def test_filter_by_judgment(company_client: AsyncClient, ready_review: str, run_id: str):
    res = await company_client.get(
        url(ready_review, run_id, "candidates"), params={"judgment": "unsuitable"}
    )

    assert [i["candidate_id"] for i in res.json()["items"]] == ["plan-b"]
    assert res.json()["pagingInfo"]["elementCount"] == 1


async def test_invalid_filter_returns_422(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(
        url(ready_review, run_id, "candidates"), params={"judgment": "적합"}
    )

    assert res.status_code == 422
    assert res.json()["code"] == "INVALID_FILTER"


async def test_candidates_paging(company_client: AsyncClient, ready_review: str, run_id: str):
    res = await company_client.get(
        url(ready_review, run_id, "candidates"), params={"pageSize": 1, "pageNumber": 2}
    )

    body = res.json()
    assert len(body["items"]) == 1
    assert body["pagingInfo"]["isLastPage"] is True
    assert body["pagingInfo"]["totalPageCount"] == 2


async def test_company_change_marks_candidates_stale(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    await company_client.patch(
        "/api/v1/companies/me", json={"profile_version": 1, "industry": "플라스틱 압출"}
    )

    res = await company_client.get(url(ready_review, run_id, "candidates"))

    assert all(i["stale_company_profile"] for i in res.json()["items"])


async def test_unfinished_run_returns_409(
    company_client: AsyncClient,
    ready_review: str,
    fake_engine: FakeEngine,
    run_queue: InlineQueue,
):
    run_queue.enabled = False
    run_id = await run_review(company_client, ready_review)

    for path in ("candidates", "candidates/plan-a", "review-queue", "tasks"):
        res = await company_client.get(url(ready_review, run_id, path))
        assert res.status_code == 409
        assert res.json()["code"] == "RESULT_NOT_READY"


async def test_failed_run_returns_409(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    fake_engine.respond = lambda: httpx.Response(503)
    run_id = await run_review(company_client, ready_review)

    res = await company_client.get(url(ready_review, run_id, "candidates"))

    assert res.status_code == 409


# --- 후보 상세 ---


async def test_candidate_detail_has_risks_checks_and_evidence(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "candidates/plan-b"))

    assert res.status_code == 200
    body = res.json()
    assert body["judgment"]["status"] == "unsuitable"
    assert [c["result"] for c in body["checks"]] == ["unmet", "needs_verification"]
    severities = {r["risk_id"]: r["severity"] for r in body["risks"]}
    assert severities == {"plan-b-r1": "high", "plan-b-r2": "medium"}
    assert body["risks"][0]["step_no"] == 1
    assert body["risks"][0]["next_action"] == "시설에 확인: 함수율 한도"
    statute = body["legal_evidence"][0]
    assert statute["search_status"] == "retrieved"
    assert statute["results"][0]["citation"] == "폐기물관리법 제2조"
    assert statute["results"][0]["effective_from"] == "2025-01-01"
    assert statute["results"][0]["applicability"] == "not_audited"
    assert body["cost"]["status"] == "missing"
    assert body["cost"]["total"] is None
    assert body["critic"]["status"] == "not_performed"
    assert body["evidence_grade"] == "C"


async def test_candidate_detail_lists_unconfirmed_items(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "candidates/plan-a"))

    unconfirmed = res.json()["unconfirmed"]
    kinds = [(u["kind"], u["ref_id"]) for u in unconfirmed]
    assert ("risk", "plan-a-r1") in kinds
    # 결과가 없는 법령 검색(ls-2, no_hits)도 미확인으로 드러남
    assert any(k == "legal_search" for k, _ in kinds)


async def test_unknown_candidate_returns_404(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "candidates/nope"))

    assert res.status_code == 404


# --- 검토 대기·확인 과제 ---


async def test_review_queue_lists_candidates_needing_check(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "review-queue"))

    body = res.json()
    assert body["router_state"] == "REVIEW"
    assert [i["candidate_id"] for i in body["items"]] == ["plan-a"]
    assert body["items"][0]["required_checks"] == ["함수율 한도", "이물 허용 기준"]
    assert body["items"][0]["assignee_role"] is None


async def test_review_queue_empty_when_engine_did_not_route_to_review(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    fake_engine.respond = lambda: httpx.Response(200, json=research_result(route="PASS"))
    run_id = await run_review(company_client, ready_review)

    res = await company_client.get(url(ready_review, run_id, "review-queue"))

    assert res.json()["items"] == []


async def test_tasks_cover_risks_and_missing_legal_evidence(
    company_client: AsyncClient, ready_review: str, run_id: str
):
    res = await company_client.get(url(ready_review, run_id, "tasks"), params={"pageSize": 100})

    items = res.json()["items"]
    risk_tasks = [t for t in items if t["risk_id"]]
    legal_tasks = [t for t in items if t["risk_id"] is None]
    assert len(risk_tasks) == 4
    assert len(legal_tasks) == 2
    assert {t["status"] for t in items} == {"open"}
    done = await company_client.get(url(ready_review, run_id, "tasks"), params={"status": "done"})
    assert done.json()["items"] == []


# --- 버전 비교 ---


async def test_compare_reports_judgment_changes(
    company_client: AsyncClient, ready_review: str, fake_engine: FakeEngine
):
    base = await run_review(company_client, ready_review)
    changed = research_result(graph_trace={"graph_generation": "gen-2"})
    changed["candidates"][1]["status"] = "needs_verification"
    changed["candidates"] = changed["candidates"][1:]
    fake_engine.respond = lambda: httpx.Response(200, json=changed)
    target = await run_review(company_client, ready_review)

    res = await company_client.get(
        f"/api/v1/reviews/{ready_review}/compare",
        params={"base_run_id": base, "target_run_id": target},
    )

    body = res.json()
    assert body["graph_changed"] is True
    changes = {(c["candidate_id"], c["field"]): c for c in body["changes"]}
    assert changes[("plan-a", "presence")]["target_value"] is False
    assert changes[("plan-b", "judgment")]["base_value"] == "unsuitable"
    assert changes[("plan-b", "judgment")]["target_value"] == "needs_check"


async def test_compare_runs_of_different_reviews_returns_422(
    company_client: AsyncClient, ready_review: str, run_id: str, fake_engine: FakeEngine
):
    other = await company_client.post(
        "/api/v1/reviews",
        json={"free_text": "다른 검토", "overrides": {"material": "PE", "quantity_kg": 10}},
    )
    other_run = await run_review(company_client, other.json()["review_id"])

    res = await company_client.get(
        f"/api/v1/reviews/{ready_review}/compare",
        params={"base_run_id": run_id, "target_run_id": other_run},
    )

    assert res.status_code == 422
    assert res.json()["code"] == "DIFFERENT_REVIEW"


async def test_other_company_cannot_read_results(
    company_client: AsyncClient, other_client: AsyncClient, ready_review: str, run_id: str
):
    for path in ("candidates", "candidates/plan-a", "review-queue", "tasks"):
        assert (await other_client.get(url(ready_review, run_id, path))).status_code == 404
    res = await other_client.get(
        f"/api/v1/reviews/{ready_review}/compare",
        params={"base_run_id": run_id, "target_run_id": run_id},
    )
    assert res.status_code == 404
