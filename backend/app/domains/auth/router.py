import logging

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.db.session import DbSession
from app.domains.auth import providers, service
from app.domains.auth.cookies import REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from app.domains.companies import service as company_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _require_provider(provider: str) -> None:
    if provider not in providers.SUPPORTED_PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unsupported provider")
    if not providers.is_configured(provider):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Provider not configured")


@router.get("/{provider}/login")
async def login(provider: str, request: Request) -> Response:
    _require_provider(provider)
    redirect_uri = f"{get_settings().backend_url}/api/v1/auth/{provider}/callback"
    client = providers.oauth.create_client(provider)
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback")
async def callback(provider: str, request: Request, db: DbSession) -> Response:
    _require_provider(provider)
    frontend = get_settings().frontend_url
    client = providers.oauth.create_client(provider)
    try:
        token = await client.authorize_access_token(
            request, claims_options=providers.claims_options(provider)
        )
        user = await service.login_or_register(db, provider, token.get("userinfo") or {})
    except (OAuthError, service.MissingSubjectError) as exc:
        logger.warning("OAuth callback failed for %s: %s", provider, type(exc).__name__)
        return RedirectResponse(f"{frontend}/login?error=oauth_failed", status.HTTP_302_FOUND)

    if user.is_withdrawn:
        return RedirectResponse(f"{frontend}/login?error=account_withdrawn", status.HTTP_302_FOUND)

    has_company = await company_service.get_company_by_owner(db, user.id) is not None
    response = RedirectResponse(
        f"{frontend}/" if has_company else f"{frontend}/onboarding", status.HTTP_302_FOUND
    )
    set_auth_cookies(response, user.id, await service.start_session(db, user.id))
    return response


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    response: Response,
    db: DbSession,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> None:
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        user_id, new_refresh_token = await service.rotate_session(db, refresh_token)
    except service.InvalidRefreshTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None
    set_auth_cookies(response, user_id, new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: DbSession,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> None:
    # No auth required: a user whose access token expired must still be able to log out.
    await service.end_session(db, refresh_token)
    clear_auth_cookies(response)
