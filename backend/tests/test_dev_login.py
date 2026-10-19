"""Dev-login criteria from docs/specs/auth-social-login.md (개발용 로그인)."""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domains.users.models import User
from app.main import create_app


async def test_dev_login_returns_usable_token(client: AsyncClient):
    res = await client.post("/api/v1/auth/dev-login", json={"email": "dev@example.com"})

    assert res.status_code == 200
    token = res.json()["access_token"]
    client.cookies.clear()
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "dev@example.com"


async def test_dev_login_without_body_uses_default_user(client: AsyncClient):
    res = await client.post("/api/v1/auth/dev-login")
    assert res.status_code == 200


async def test_repeat_dev_login_reuses_user(client: AsyncClient, db: AsyncSession):
    await client.post("/api/v1/auth/dev-login", json={"email": "dev@example.com"})
    await client.post("/api/v1/auth/dev-login", json={"email": "dev@example.com"})

    assert await db.scalar(select(func.count()).select_from(User)) == 1


def test_prod_app_has_no_dev_login_route():
    prod = Settings(
        app_env="prod",
        jwt_secret="p" * 32,
        session_secret="s" * 32,
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    paths = create_app(prod).openapi()["paths"]

    assert "/api/v1/auth/dev-login" not in paths
    assert "/api/v1/users/me" in paths
