import os

# Must be set before app modules read settings.
os.environ.update(
    APP_ENV="test",
    DATABASE_URL="sqlite+aiosqlite://",
    JWT_SECRET="test-secret-at-least-32-bytes-long!!",
    GOOGLE_CLIENT_ID="test-google-client",
    MICROSOFT_CLIENT_ID="test-microsoft-client",
    FRONTEND_URL="http://frontend.test",
)

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.security import create_token  # noqa: E402
from app.db.all_models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.domains.auth.cookies import ACCESS_COOKIE  # noqa: E402
from app.domains.users.models import User  # noqa: E402
from app.main import app  # noqa: E402

# CI sets TEST_DATABASE_URL to a PostgreSQL service; locally tests use in-memory SQLite.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if TEST_DATABASE_URL:
        engine = create_async_engine(TEST_DATABASE_URL)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def user(db: AsyncSession) -> User:
    user = User(
        provider="google",
        provider_subject="manager-sub",
        email="manager@example.com",
        name="담당자",
    )
    db.add(user)
    await db.commit()
    return user


@pytest.fixture
def auth_client(client: AsyncClient, user: User) -> AsyncClient:
    client.cookies.set(ACCESS_COOKIE, create_token(user.id, "access"))
    return client


# 검토 관련 테스트가 함께 쓰는 기업 (주요 폐기물이 하나라 소재 기본값이 생김)
COMPANY_PAYLOAD = {
    "company_name": "가상사출(주)",
    "contact_email": "manager@example.com",
    "industry": "플라스틱 사출 성형",
    "site_name": "시흥 1공장",
    "site_address": "경기도 시흥시 정왕동",
    "site_facilities": ["혼합시설"],
    "main_products": ["자동차 내장 부품"],
    "main_waste_types": [{"category": "PP"}],
}


@pytest.fixture
async def company_client(auth_client: AsyncClient) -> AsyncClient:
    res = await auth_client.post("/api/v1/companies", json=COMPANY_PAYLOAD)
    assert res.status_code == 201
    return auth_client


@pytest.fixture
async def other_client(client: AsyncClient, db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """다른 기업 사용자. 접근 격리 확인용."""
    other = User(
        provider="google",
        provider_subject="other-sub",
        email="other@example.com",
        name="다른담당자",
    )
    db.add(other)
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.cookies.set(ACCESS_COOKIE, create_token(other.id, "access"))
        res = await c.post("/api/v1/companies", json=COMPANY_PAYLOAD)
        assert res.status_code == 201
        yield c
