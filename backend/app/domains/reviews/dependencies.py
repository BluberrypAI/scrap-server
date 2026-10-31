import uuid
from typing import Annotated

from fastapi import Depends

from app.core.errors import ConflictError, ErrorCode, NotFoundError
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service as company_service
from app.domains.companies.models import Company
from app.domains.reviews import service
from app.domains.reviews.models import Review


async def get_my_company(user: CurrentUser, db: DbSession) -> Company:
    company = await company_service.get_company_by_owner(db, user.id)
    if company is None:
        raise ConflictError(ErrorCode.COMPANY_REQUIRED, "기업 정보를 먼저 등록해야 함")
    return company


MyCompany = Annotated[Company, Depends(get_my_company)]


async def get_my_review(review_id: uuid.UUID, company: MyCompany, db: DbSession) -> Review:
    review = await service.get_review(db, company.id, review_id)
    if review is None:
        raise NotFoundError("검토를 찾을 수 없음")
    return review


MyReview = Annotated[Review, Depends(get_my_review)]
