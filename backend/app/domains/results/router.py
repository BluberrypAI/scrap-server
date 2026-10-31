import math
import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnprocessableError,
)
from app.db.session import DbSession
from app.domains.companies.schemas import PagingInfo
from app.domains.results import transform
from app.domains.results.schemas import (
    CandidateDetail,
    CandidateItem,
    CandidatePage,
    Comparison,
    ReviewQueue,
    TaskItem,
    TaskPage,
)
from app.domains.reviews.dependencies import MyCompany, MyReview
from app.domains.reviews.models import Review
from app.domains.runs import service as run_service
from app.domains.runs.dependencies import MyRun
from app.domains.runs.models import FINISHED_WITH_RESULT, Run

router = APIRouter(tags=["results"])

RUN = "/reviews/{review_id}/runs/{run_id}"
_NOT_READY = {409: {"description": "실행이 끝나지 않았거나 실패함 (RESULT_NOT_READY)"}}


def _result(run: Run) -> dict[str, Any]:
    """결과가 있는 실행의 엔진 응답. 없으면 409 RESULT_NOT_READY."""
    if run.status not in FINISHED_WITH_RESULT or run.result is None:
        raise ConflictError(
            ErrorCode.RESULT_NOT_READY, f"실행 결과가 없음 (현재 상태: {run.status.value})"
        )
    return run.result


def _stale(run: Run, company_profile_version: int) -> bool:
    return company_profile_version != run.pinned_versions.get("company_profile_version")


def _page(items: list, page_number: int, page_size: int) -> tuple[list, PagingInfo]:
    total = len(items)
    total_pages = math.ceil(total / page_size)
    rows = items[(page_number - 1) * page_size : page_number * page_size]
    return rows, PagingInfo(
        current_page_number=page_number,
        page_size=page_size,
        element_count=total,
        total_page_count=total_pages,
        is_last_page=page_number >= total_pages,
        is_empty=not rows,
    )


@router.get(
    f"{RUN}/candidates",
    response_model=CandidatePage,
    summary="조합 후보 목록",
    description="엔진이 찾은 모든 후보. 어떤 후보도 숨기지 않음. judgment로 거를 수 있음 "
    "(suitable, needs_check, unsuitable, verification_failed, excluded). "
    "엔진은 적합 판정·순위·비용·탄소를 내지 않으므로 해당 값은 null·missing.",
    responses={**_NOT_READY, 422: {"description": "잘못된 judgment (INVALID_FILTER)"}},
)
async def list_candidates(
    run: MyRun,
    company: MyCompany,
    judgment: str | None = None,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> CandidatePage:
    if judgment is not None and judgment not in transform.JUDGMENTS:
        raise UnprocessableError(
            ErrorCode.INVALID_FILTER, f"judgment는 {', '.join(transform.JUDGMENTS)} 중 하나"
        )
    result = _result(run)
    stale = _stale(run, company.profile_version)
    items = [
        transform.list_item(c, stale)
        for c in result.get("candidates", [])
        if judgment is None or transform.judgment_of(c) == judgment
    ]
    rows, paging = _page(items, page_number, page_size)
    return CandidatePage(
        items=[CandidateItem(**row) for row in rows],
        paging_info=paging,
    )


@router.get(
    f"{RUN}/candidates/{{candidate_id}}",
    response_model=CandidateDetail,
    summary="조합 상세",
    description="공정 경로, 단계별 시설 조건 대조(checks), 리스크, "
    "법령 근거(원문·조문·시행일·출처), 미확인 목록. "
    "법령 근거의 applicability는 엔진이 적용성을 검토하지 않아 not_audited.",
    responses=_NOT_READY,
)
async def read_candidate(candidate_id: str, run: MyRun, company: MyCompany) -> CandidateDetail:
    result = _result(run)
    candidate = next(
        (c for c in result.get("candidates", []) if c["plan"]["plan_id"] == candidate_id), None
    )
    if candidate is None:
        raise NotFoundError("후보를 찾을 수 없음")
    data = transform.detail(candidate, result, _stale(run, company.profile_version))
    return CandidateDetail(**data, evidence_grade=run.pinned_versions.get("evidence_grade"))


@router.get(
    f"{RUN}/review-queue",
    response_model=ReviewQueue,
    summary="전문가 검토 대기 목록",
    description="엔진 판정이 REVIEW일 때 확인이 필요한(needs_check) 후보와 확인할 항목.",
    responses=_NOT_READY,
)
async def read_review_queue(run: MyRun) -> ReviewQueue:
    result = _result(run)
    return ReviewQueue(
        router_state=run.router_state,
        items=transform.review_queue(result, run.router_state),
    )


@router.get(
    f"{RUN}/tasks",
    response_model=TaskPage,
    summary="확인 과제 목록",
    description="리스크마다, 결과가 없는 법령 검색마다 확인 과제 하나. status로 거름.",
    responses=_NOT_READY,
)
async def list_tasks(
    run: MyRun,
    status: str | None = Query(None, pattern="^(open|done)$"),
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> TaskPage:
    result = _result(run)
    items = [{**task, "status": "open"} for task in transform.tasks(result)]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    rows, paging = _page(items, page_number, page_size)
    return TaskPage(items=[TaskItem(**row) for row in rows], paging_info=paging)


async def _run_for_compare(db: DbSession, review: Review, run_id: uuid.UUID) -> Run:
    run = await run_service.get_run(db, review.id, run_id)
    if run is not None:
        return run
    # 같은 기업의 다른 검토 실행이면 422. 다른 기업 실행은 존재 여부를 드러내지 않고 404
    other = await db.scalar(
        select(Run.id)
        .join(Review, Review.id == Run.review_id)
        .where(Run.id == run_id, Review.company_id == review.company_id)
    )
    if other is not None:
        raise UnprocessableError(
            ErrorCode.DIFFERENT_REVIEW, "같은 검토의 실행끼리만 비교할 수 있음"
        )
    raise NotFoundError("실행을 찾을 수 없음")


@router.get(
    "/reviews/{review_id}/compare",
    response_model=Comparison,
    summary="버전 비교",
    description="같은 검토의 두 실행에서 후보별 판정·심각 리스크 수·사유가 어떻게 달라졌는지.",
    responses={**_NOT_READY, 422: {"description": "다른 검토의 실행 (DIFFERENT_REVIEW)"}},
)
async def compare_runs(
    review: MyReview,
    db: DbSession,
    base_run_id: uuid.UUID,
    target_run_id: uuid.UUID,
) -> Comparison:
    base = await _run_for_compare(db, review, base_run_id)
    target = await _run_for_compare(db, review, target_run_id)
    base_result, target_result = _result(base), _result(target)
    return Comparison(
        base_run_id=base.id,
        target_run_id=target.id,
        graph_changed=base.pinned_versions.get("graph_trace")
        != target.pinned_versions.get("graph_trace"),
        changes=transform.compare(base_result, target_result),
    )
