"""Local-only login that skips OAuth, so protected APIs can be tried from Swagger.

Registered by app.main only when APP_ENV is local or test; absent in prod.
"""

import uuid

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.core.security import create_token
from app.db.session import DbSession
from app.domains.auth import service
from app.domains.auth.cookies import set_auth_cookies

DEV_PROVIDER = "dev"

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    email: str = Field(default="dev@example.com", max_length=320)
    name: str = Field(default="개발자", max_length=200)


class DevLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID


@router.post(
    "/dev-login",
    response_model=DevLoginResponse,
    summary="개발용 로그인 (로컬 전용)",
    description="OAuth 키 없이 로그인함. 받은 access_token을 Swagger **Authorize**에 넣거나, "
    "같은 브라우저라면 설정된 쿠키로 바로 다른 API를 호출할 수 있음.",
    responses={403: {"description": "탈퇴 처리 중인 사용자"}},
)
async def dev_login(response: Response, db: DbSession, data: DevLoginRequest | None = None):
    data = data or DevLoginRequest()
    user = await service.login_or_register(
        db, DEV_PROVIDER, {"sub": data.email, "email": data.email, "name": data.name}
    )
    if user.is_withdrawn:
        raise AppError(
            status.HTTP_403_FORBIDDEN, ErrorCode.ACCOUNT_WITHDRAWN, "탈퇴 처리 중인 계정"
        )
    set_auth_cookies(response, user.id, await service.start_session(db, user.id))
    return DevLoginResponse(access_token=create_token(user.id, "access"), user_id=user.id)
