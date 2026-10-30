import math
import uuid
from typing import Literal

from fastapi import APIRouter, Query, status

from app.core.errors import ErrorCode, UnprocessableError
from app.db.session import DbSession
from app.domains.companies.schemas import PagingInfo
from app.domains.reviews import intake as intake_rules
from app.domains.reviews import service
from app.domains.reviews.dependencies import MyCompany, MyReview
from app.domains.reviews.models import Review
from app.domains.reviews.schemas import (
    MAX_FREE_TEXT,
    IntakeGroups,
    IntakeItem,
    IntakeQuestion,
    IntakeRead,
    IntakeUpdate,
    IntakeUpdateResult,
    ReviewCreate,
    ReviewCreated,
    ReviewListItem,
    ReviewPage,
    ReviewRead,
)
from app.domains.runs import service as run_service

router = APIRouter(prefix="/reviews", tags=["reviews"])

_COMPANY_REQUIRED = {409: {"description": "기업 정보 미등록 (COMPANY_REQUIRED)"}}


def _list_item(review: Review, latest_run_id: uuid.UUID | None) -> ReviewListItem:
    return ReviewListItem(
        review_id=review.id,
        title=review.title,
        status=review.status,
        created_at=review.created_at,
        latest_run_id=latest_run_id,
    )


@router.post(
    "",
    response_model=ReviewCreated,
    status_code=status.HTTP_201_CREATED,
    summary="검토 생성 (자연어 상황 입력)",
    description="자연어 원문과 구조화 항목(overrides)을 받아 검토를 만듦. "
    "기업 기본값은 미확인 값으로만 들어가며, 사용자가 확인해야 확인된 값이 됨.",
    responses={
        **_COMPANY_REQUIRED,
        422: {"description": "EMPTY_INPUT, TEXT_TOO_LONG, VALIDATION_ERROR"},
    },
)
async def create_review(data: ReviewCreate, company: MyCompany, db: DbSession) -> ReviewCreated:
    try:
        review = await service.create_review(db, company, data)
    except service.EmptyInputError:
        raise UnprocessableError(ErrorCode.EMPTY_INPUT, "상황 설명을 입력해야 함") from None
    except service.TextTooLongError:
        raise UnprocessableError(
            ErrorCode.TEXT_TOO_LONG, f"상황 설명은 {MAX_FREE_TEXT}자 이하여야 함"
        ) from None
    return ReviewCreated(
        review_id=review.id,
        status=review.status,
        company_profile_version=review.company_profile_version,
    )


@router.get(
    "",
    response_model=ReviewPage,
    summary="검토 목록",
    description="내 기업의 검토 목록. sort는 created_at,desc(기본) 또는 created_at,asc.",
    responses=_COMPANY_REQUIRED,
)
async def list_reviews(
    company: MyCompany,
    db: DbSession,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    sort: Literal["created_at,desc", "created_at,asc"] = "created_at,desc",
) -> ReviewPage:
    order = "asc" if sort.endswith("asc") else "desc"
    rows, total = await service.list_reviews(db, company.id, page_number, page_size, order)
    latest = await run_service.latest_run_ids(db, [r.id for r in rows])
    total_pages = math.ceil(total / page_size)
    return ReviewPage(
        items=[_list_item(r, latest.get(r.id)) for r in rows],
        paging_info=PagingInfo(
            current_page_number=page_number,
            page_size=page_size,
            element_count=total,
            total_page_count=total_pages,
            is_last_page=page_number >= total_pages,
            is_empty=not rows,
        ),
    )


@router.get("/{review_id}", response_model=ReviewRead, summary="검토 상세")
async def read_review(review: MyReview, db: DbSession) -> ReviewRead:
    latest = await run_service.latest_run_ids(db, [review.id])
    return ReviewRead(
        **_list_item(review, latest.get(review.id)).model_dump(),
        free_text=review.free_text,
        company_profile_version=review.company_profile_version,
        intake_version=review.intake_version,
    )


def _intake_read(review: Review) -> IntakeRead:
    confirmed, unconfirmed = intake_rules.grouped(review.intake)
    return IntakeRead(
        status=review.status,
        intake_version=review.intake_version,
        intake=IntakeGroups(
            confirmed=[IntakeItem(**i) for i in confirmed],
            unconfirmed=[IntakeItem(**i) for i in unconfirmed],
        ),
        questions=[IntakeQuestion(**q) for q in intake_rules.questions(review.intake)],
    )


@router.get(
    "/{review_id}/intake",
    response_model=IntakeRead,
    summary="입력 항목 정리 조회",
    description="확인된 값, 미확인 값(기업 기본값), 보완 질문을 돌려줌. "
    "required=true인 질문이 남아 있으면 status는 intake_pending.",
)
async def read_intake(review: MyReview) -> IntakeRead:
    return _intake_read(review)


@router.patch(
    "/{review_id}/intake",
    response_model=IntakeUpdateResult,
    summary="보완 질문 답변",
    description="답변한 항목은 확인된 값이 됨. value=null은 '모름'으로 기록함. "
    "quantity_kg는 unit=t를 보내면 kg로 환산함. 값이 바뀌면 intake_version이 1 오름.",
)
async def update_intake(data: IntakeUpdate, review: MyReview, db: DbSession) -> IntakeUpdateResult:
    answers = {a.field: a.value for a in data.answers}
    await service.update_intake(db, review, answers)
    return IntakeUpdateResult(status=review.status, intake_version=review.intake_version)
