from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import InvalidTokenError, decode_token
from app.db.session import DbSession
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
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if not token:
        raise unauthorized
    try:
        user_id = decode_token(token, "access")
    except InvalidTokenError:
        raise unauthorized from None
    user = await user_repo.get_user(db, user_id)
    # Withdrawn users are cut off at once, even with an unexpired access token.
    if user is None or user.is_withdrawn:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
