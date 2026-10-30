import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnprocessableError,
)
from app.db.session import DbSession, get_session_factory
from app.domains.companies.schemas import PagingInfo
from app.domains.reviews.dependencies import MyReview
from app.domains.runs import service, stages
from app.domains.runs.dependencies import MyRun
from app.domains.runs.engine_client import EngineClient, get_engine_client
from app.domains.runs.models import Run
from app.domains.runs.schemas import (
    RunCreate,
    RunCreated,
    RunErrorInfo,
    RunListItem,
    RunPage,
    RunRead,
    RunStage,
)
from app.domains.runs.worker import InProcessRunQueue, get_run_queue
from app.domains.supplements import service as supplement_service

router = APIRouter(prefix="/reviews/{review_id}/runs", tags=["runs"])

Engine = Annotated[EngineClient | None, Depends(get_engine_client)]
Queue = Annotated[InProcessRunQueue, Depends(get_run_queue)]
SessionFactory = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


def require_engine(engine: EngineClient | None) -> EngineClient:
    if engine is None:
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.ENGINE_UNAVAILABLE,
            "AI 엔진이 설정되지 않음 (AI_BASE_URL)",
        )
    return engine


async def start_run(
    db: DbSession,
    review: MyReview,
    engine: EngineClient,
    queue: InProcessRunQueue,
    session_factory: async_sessionmaker[AsyncSession],
    intake_version: int,
    document_ids: list,
    parent: Run | None = None,
    rerun_from_stage: str | None = None,
    supplement_ids: list | None = None,
) -> Run:
    """실행을 만들고 워커에 넘김. 재실행(review-risks-supplements)도 같은 경로를 씀."""
    try:
        run = await service.create_run(
            db,
            review,
            intake_version,
            document_ids,
            parent,
            rerun_from_stage,
            supplement_ids or [],
        )
    except service.IntakeVersionConflictError:
        raise ConflictError(
            ErrorCode.VERSION_CONFLICT, "입력이 그 사이 바뀜. 다시 조회한 뒤 실행해야 함"
        ) from None
    except service.IntakeIncompleteError:
        raise ConflictError(
            ErrorCode.INTAKE_INCOMPLETE, "필수 입력이 확인되지 않음. 보완 질문에 먼저 답해야 함"
        ) from None
    except service.RunInProgressError:
        raise ConflictError(ErrorCode.RUN_IN_PROGRESS, "이미 진행 중인 실행이 있음") from None
    except service.InvalidDocumentsError:
        raise UnprocessableError(
            ErrorCode.VALIDATION_ERROR, "이 검토에 올린 문서만 지정할 수 있음"
        ) from None
    await queue.enqueue(run.id, session_factory, engine)
    return run


@router.post(
    "",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="검토 실행",
    description="실행을 queued로 만들고 바로 응답함. AI 엔진 호출은 워커가 하며, "
    "진행 상태는 GET /runs/{runId}로 확인함. 엔진에는 확인된 입력만 보냄.",
    responses={
        409: {"description": "INTAKE_INCOMPLETE, RUN_IN_PROGRESS, VERSION_CONFLICT"},
        503: {"description": "AI 엔진 미설정 (ENGINE_UNAVAILABLE)"},
    },
)
async def create_run(
    data: RunCreate,
    review: MyReview,
    db: DbSession,
    engine: Engine,
    queue: Queue,
    session_factory: SessionFactory,
) -> RunCreated:
    run = await start_run(
        db,
        review,
        require_engine(engine),
        queue,
        session_factory,
        data.intake_version,
        data.document_ids,
    )
    return RunCreated(run_id=run.id, status=run.status, pinned_versions=run.pinned_versions)


def _list_item(run: Run) -> RunListItem:
    return RunListItem(
        run_id=run.id,
        parent_run_id=run.parent_run_id,
        rerun_from_stage=run.rerun_from_stage,
        status=run.status,
        created_at=run.created_at,
    )


@router.get(
    "",
    response_model=RunPage,
    summary="실행 이력",
    description="최신 실행부터. 재실행은 parent_run_id로 원래 실행을 가리킴.",
)
async def list_runs(
    review: MyReview,
    db: DbSession,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> RunPage:
    rows, total = await service.list_runs(db, review.id, page_number, page_size)
    total_pages = math.ceil(total / page_size)
    return RunPage(
        items=[_list_item(r) for r in rows],
        paging_info=PagingInfo(
            current_page_number=page_number,
            page_size=page_size,
            element_count=total,
            total_page_count=total_pages,
            is_last_page=page_number >= total_pages,
            is_empty=not rows,
        ),
    )


@router.get(
    "/{run_id}",
    response_model=RunRead,
    summary="실행 상태",
    description="상태와 단계별 상태. 진행 화면이 polling함. 과거 실행을 열 때도 씀.",
)
async def read_run(run: MyRun) -> RunRead:
    result = run.result or {}
    return RunRead(
        **_list_item(run).model_dump(),
        stages=[RunStage(**s) for s in run.stages],
        router_state=run.router_state,
        pinned_versions=run.pinned_versions,
        error=RunErrorInfo(code=run.error_code, message=run.error_message)
        if run.error_code
        else None,
        coverage=result.get("coverage"),
        limitations=result.get("limitations", []),
        next_actions=result.get("next_actions", []),
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


class RerunCreate(BaseModel):
    supplement_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=50, description="반영할 추가 자료. 모두 counted_in_judgment=true"
    )


class RerunCreated(BaseModel):
    new_run_id: uuid.UUID
    rerun_from_stage: str
    reused_stages: list[str]


@router.post(
    "/{run_id}/rerun",
    response_model=RerunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="추가 자료 반영 재실행",
    description="원래 실행의 근거 문서와 현재 입력으로 새 실행을 만듦. AI 엔진에 일부 단계만 다시 "
    "실행하는 기능이 없어 research 단계부터 다시 실행함 (입력 정리만 재사용).",
    responses={
        409: {"description": "NO_APPLICABLE_SUPPLEMENT, RUN_IN_PROGRESS, INTAKE_INCOMPLETE"},
        503: {"description": "ENGINE_UNAVAILABLE"},
    },
)
async def rerun(
    data: RerunCreate,
    run: MyRun,
    review: MyReview,
    db: DbSession,
    engine: Engine,
    queue: Queue,
    session_factory: SessionFactory,
) -> RerunCreated:
    engine_client = require_engine(engine)
    supplements = await supplement_service.get_many(db, review.id, data.supplement_ids)
    if len(supplements) != len(set(data.supplement_ids)):
        raise NotFoundError("추가 자료를 찾을 수 없음")
    if not all(supplement_service.counted_in_judgment(s) for s in supplements):
        raise ConflictError(
            ErrorCode.NO_APPLICABLE_SUPPLEMENT,
            "물량이 맞고 검수된 추가 자료만 재실행에 반영할 수 있음",
        )
    new_run = await start_run(
        db,
        review,
        engine_client,
        queue,
        session_factory,
        review.intake_version,
        [uuid.UUID(d) for d in run.pinned_versions.get("document_ids", [])],
        parent=run,
        rerun_from_stage=stages.RESEARCH,
        supplement_ids=[s.id for s in supplements],
    )
    return RerunCreated(
        new_run_id=new_run.id,
        rerun_from_stage=stages.RESEARCH,
        reused_stages=[stages.INTAKE],
    )
