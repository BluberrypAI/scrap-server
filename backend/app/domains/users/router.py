from fastapi import APIRouter

from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service as company_service
from app.domains.users.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser, db: DbSession) -> UserRead:
    company = await company_service.get_company_by_owner(db, user.id)
    return UserRead(id=user.id, email=user.email, name=user.name, has_company=company is not None)
