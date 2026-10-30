import uuid
from typing import Annotated

from fastapi import Depends

from app.core.errors import NotFoundError
from app.db.session import DbSession
from app.domains.reviews.dependencies import MyReview
from app.domains.runs import service
from app.domains.runs.models import Run


async def get_my_run(run_id: uuid.UUID, review: MyReview, db: DbSession) -> Run:
    run = await service.get_run(db, review.id, run_id)
    if run is None:
        raise NotFoundError("실행을 찾을 수 없음")
    return run


MyRun = Annotated[Run, Depends(get_my_run)]
