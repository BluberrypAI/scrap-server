from fastapi import APIRouter, Response

from app.db.session import DbSession
from app.domains.auth.cookies import clear_auth_cookies
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service as company_service
from app.domains.users import service
from app.domains.users.schemas import UserRead, WithdrawRead, WithdrawRequest

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser, db: DbSession) -> UserRead:
    company = await company_service.get_company_by_user(db, user.id)
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        provider=user.provider,
        company_id=company.id if company else None,
    )


@router.post(
    "/me/withdraw",
    response_model=WithdrawRead,
    summary="회원 탈퇴",
    description="즉시 비활성화하고 모든 세션을 종료함. 삭제 예정일(기본 30일 뒤)에 "
    "사용자·기업 정보를 삭제함. 탈퇴는 철회할 수 없고, 유예 기간 중 로그인은 차단됨.",
)
async def withdraw(
    data: WithdrawRequest, user: CurrentUser, db: DbSession, response: Response
) -> WithdrawRead:
    scheduled = await service.withdraw(db, user)
    clear_auth_cookies(response)
    return WithdrawRead(deletion_scheduled_at=scheduled)
