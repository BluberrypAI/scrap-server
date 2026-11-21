import uuid

from starlette.responses import Response

from app.core.config import get_settings
from app.core.security import create_token, decode_refresh_token

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
REFRESH_PATH = "/api/v1/auth"


def _cookie_kwargs() -> dict:
    s = get_settings()
    return {
        "httponly": True,
        "secure": s.cookie_secure,
        "samesite": s.cookie_samesite,
        "domain": s.cookie_domain,
    }


def set_access_cookie(
    response: Response, user_id: uuid.UUID, session_id: uuid.UUID | None = None
) -> None:
    s = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        create_token(user_id, "access", session_id),
        max_age=s.access_token_expire_minutes * 60,
        path="/",
        **_cookie_kwargs(),
    )


def set_auth_cookies(
    response: Response, user_id: uuid.UUID, refresh_token: str, *, guest: bool = False
) -> None:
    """refresh_token must come from auth.service.start_session/rotate_session (DB-recorded)."""
    s = get_settings()
    session_id = decode_refresh_token(refresh_token)[1] if guest else None
    set_access_cookie(response, user_id, session_id)
    # Scoped to the auth routes so the long-lived token is not sent on every API call.
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=s.refresh_token_expire_days * 86400,
        path=REFRESH_PATH,
        **_cookie_kwargs(),
    )


def clear_auth_cookies(response: Response) -> None:
    kwargs = _cookie_kwargs()
    response.delete_cookie(ACCESS_COOKIE, path="/", **kwargs)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, **kwargs)
