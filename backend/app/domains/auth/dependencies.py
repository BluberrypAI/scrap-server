from typing import Annotated

from fastapi import Cookie, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError, AuthRequiredError, ErrorCode
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import DbSession
from app.domains.auth import service
from app.domains.auth.cookies import ACCESS_COOKIE
from app.domains.users import repository as user_repo
from app.domains.users.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    access_cookie: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> User:
    token = credentials.credentials if credentials else access_cookie
    if not token:
        raise AuthRequiredError
    try:
        user_id, session_id = decode_access_token(token)
    except InvalidTokenError:
        raise AuthRequiredError from None
    user = await user_repo.get_user(db, user_id)
    # Withdrawn users are cut off at once, even with an unexpired access token.
    if user is None or user.is_withdrawn:
        raise AuthRequiredError
    if user.is_guest and not await service.guest_session_active(db, user.id, session_id):
        raise AuthRequiredError
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_regular_user(user: CurrentUser) -> User:
    if user.is_guest:
        raise AppError(403, ErrorCode.FORBIDDEN, "링크 참여 계정에는 이 작업 권한이 없습니다.")
    return user


RegularUser = Annotated[User, Depends(require_regular_user)]
