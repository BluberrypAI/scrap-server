"""Completion criteria from docs/specs/auth-social-login.md."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_token, decode_refresh_token
from app.domains.auth import providers
from app.domains.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.domains.auth.models import RefreshToken
from app.domains.auth.service import login_or_register, start_session
from app.domains.users.models import SocialAccount, User

GOOGLE_USERINFO = {"sub": "google-sub-1", "email": "a@gmail.com", "name": "김담당"}


class FakeOAuthClient:
    def __init__(self, userinfo: dict[str, Any]):
        self.userinfo = userinfo

    async def authorize_access_token(self, request, **kwargs) -> dict[str, Any]:
        return {"access_token": "x", "userinfo": self.userinfo}


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch):
    def install(userinfo: dict[str, Any]) -> None:
        monkeypatch.setattr(
            providers.oauth, "create_client", lambda name: FakeOAuthClient(userinfo)
        )

    return install


async def count(db: AsyncSession, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def active_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    )
    return await db.scalar(stmt)


async def is_revoked(db: AsyncSession, refresh_token: str) -> bool:
    _, token_id = decode_refresh_token(refresh_token)
    stmt = select(RefreshToken.revoked_at).where(RefreshToken.id == token_id)
    return await db.scalar(stmt) is not None


def use_refresh_cookie(client: AsyncClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, token)


async def test_first_login_creates_user_and_social_account(db: AsyncSession):
    user = await login_or_register(db, "google", GOOGLE_USERINFO)

    assert user.email == "a@gmail.com"
    assert await count(db, User) == 1
    assert await count(db, SocialAccount) == 1


async def test_repeat_login_reuses_existing_user(db: AsyncSession):
    first = await login_or_register(db, "google", GOOGLE_USERINFO)
    second = await login_or_register(db, "google", GOOGLE_USERINFO)

    assert first.id == second.id
    assert await count(db, User) == 1


async def test_same_subject_on_other_provider_is_a_different_user(db: AsyncSession):
    google = await login_or_register(db, "google", GOOGLE_USERINFO)
    microsoft = await login_or_register(db, "microsoft", GOOGLE_USERINFO)

    assert google.id != microsoft.id


async def test_microsoft_personal_account_falls_back_to_preferred_username(db: AsyncSession):
    user = await login_or_register(
        db, "microsoft", {"sub": "ms-sub", "preferred_username": "kim@outlook.com"}
    )
    assert user.email == "kim@outlook.com"


async def test_callback_sets_cookies_and_redirects_to_onboarding(
    client: AsyncClient, fake_provider
):
    fake_provider(GOOGLE_USERINFO)

    res = await client.get("/api/v1/auth/google/callback")

    assert res.status_code == 302
    assert res.headers["location"] == "http://frontend.test/onboarding"
    assert ACCESS_COOKIE in res.cookies
    assert REFRESH_COOKIE in res.cookies
    assert "httponly" in res.headers["set-cookie"].lower()


async def test_callback_records_refresh_token(client: AsyncClient, db: AsyncSession, fake_provider):
    fake_provider(GOOGLE_USERINFO)

    await client.get("/api/v1/auth/google/callback")

    assert await count(db, RefreshToken) == 1


async def test_withdrawn_user_callback_redirects_without_cookies(
    client: AsyncClient, db: AsyncSession, fake_provider
):
    user = await login_or_register(db, "google", GOOGLE_USERINFO)
    user.withdrawn_at = datetime.now(UTC)
    await db.commit()
    fake_provider(GOOGLE_USERINFO)

    res = await client.get("/api/v1/auth/google/callback")

    assert res.status_code == 302
    assert res.headers["location"] == "http://frontend.test/login?error=account_withdrawn"
    assert ACCESS_COOKIE not in res.cookies
    assert await count(db, RefreshToken) == 0


async def test_callback_without_subject_redirects_with_error(client: AsyncClient, fake_provider):
    fake_provider({"email": "no-sub@example.com"})

    res = await client.get("/api/v1/auth/google/callback")

    assert res.status_code == 302
    assert res.headers["location"] == "http://frontend.test/login?error=oauth_failed"


async def test_unsupported_provider_returns_404(client: AsyncClient):
    res = await client.get("/api/v1/auth/kakao/login")
    assert res.status_code == 404


async def test_me_without_token_returns_401(client: AsyncClient):
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401


async def test_me_with_token(auth_client: AsyncClient, user: User):
    res = await auth_client.get("/api/v1/users/me")

    assert res.status_code == 200
    assert res.json() == {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "provider": "google",
        "company_id": None,
    }


async def test_me_accepts_bearer_header(client: AsyncClient, user: User):
    token = create_token(user.id, "access")
    res = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


async def test_refresh_rotates_tokens(client: AsyncClient, db: AsyncSession, user: User):
    old = await start_session(db, user.id)
    use_refresh_cookie(client, old)

    res = await client.post("/api/v1/auth/refresh")

    assert res.status_code == 204
    assert ACCESS_COOKIE in res.cookies
    new = res.cookies[REFRESH_COOKIE]
    assert new != old
    assert await is_revoked(db, old)
    assert not await is_revoked(db, new)


async def test_reused_refresh_token_revokes_all_sessions(
    client: AsyncClient, db: AsyncSession, user: User
):
    old = await start_session(db, user.id)
    await start_session(db, user.id)  # another device
    use_refresh_cookie(client, old)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 204

    use_refresh_cookie(client, old)
    res = await client.post("/api/v1/auth/refresh")

    assert res.status_code == 401
    assert await active_sessions(db, user.id) == 0


async def test_refresh_token_unknown_to_db_returns_401(client: AsyncClient, user: User):
    use_refresh_cookie(client, create_token(user.id, "refresh", uuid.uuid4()))

    res = await client.post("/api/v1/auth/refresh")

    assert res.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient, db: AsyncSession, user: User):
    token = await start_session(db, user.id)
    use_refresh_cookie(client, token)

    res = await client.post("/api/v1/auth/logout")

    assert res.status_code == 204
    assert await is_revoked(db, token)
    use_refresh_cookie(client, token)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_without_cookie_returns_204(client: AsyncClient):
    res = await client.post("/api/v1/auth/logout")
    assert res.status_code == 204


async def test_access_token_cannot_be_used_as_refresh(client: AsyncClient, user: User):
    client.cookies.set(REFRESH_COOKIE, create_token(user.id, "access"))

    res = await client.post("/api/v1/auth/refresh")

    assert res.status_code == 401


async def test_refresh_token_cannot_be_used_as_access(client: AsyncClient, user: User):
    client.cookies.set(ACCESS_COOKIE, create_token(user.id, "refresh"))

    res = await client.get("/api/v1/users/me")

    assert res.status_code == 401


@pytest.mark.parametrize(
    ("claims", "issuer", "expected"),
    [
        ({"tid": "abc"}, "https://login.microsoftonline.com/abc/v2.0", True),
        ({"tid": "abc"}, "https://login.microsoftonline.com/other/v2.0", False),
        ({"tid": "abc"}, "https://evil.example.com/abc/v2.0", False),
        ({}, "https://login.microsoftonline.com//v2.0", False),
    ],
)
def test_microsoft_issuer_must_match_tenant(claims, issuer, expected):
    assert providers.validate_microsoft_issuer(claims, issuer) is expected
