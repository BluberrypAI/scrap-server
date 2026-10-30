import uuid
from typing import Annotated, Any

from fastapi import Depends

from app.core.errors import ConflictError, ErrorCode, NotFoundError
from app.db.session import DbSession
from app.domains.reviews.dependencies import MyReview
from app.domains.runs import service
from app.domains.runs.models import FINISHED_WITH_RESULT, Run


async def get_my_run(run_id: uuid.UUID, review: MyReview, db: DbSession) -> Run:
    run = await service.get_run(db, review.id, run_id)
    if run is None:
        raise NotFoundError("실행을 찾을 수 없음")
    return run


MyRun = Annotated[Run, Depends(get_my_run)]


def result_of(run: Run) -> dict[str, Any]:
    """결과가 있는 실행의 엔진 응답. 없으면 409 RESULT_NOT_READY."""
    if run.status not in FINISHED_WITH_RESULT or run.result is None:
        raise ConflictError(
            ErrorCode.RESULT_NOT_READY, f"실행 결과가 없음 (현재 상태: {run.status.value})"
        )
    return run.result


def find_candidate(result: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    candidate = next(
        (c for c in result.get("candidates", []) if c["plan"]["plan_id"] == candidate_id), None
    )
    if candidate is None:
        raise NotFoundError("후보를 찾을 수 없음")
    return candidate
