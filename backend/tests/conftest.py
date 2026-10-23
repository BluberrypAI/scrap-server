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
from app.domains.users.models import SocialAccount, User  # noqa: E402
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
    user = User(email="manager@example.com", name="담당자")
    db.add(user)
    await db.flush()
    db.add(SocialAccount(user_id=user.id, provider="google", provider_subject="manager-sub"))
    await db.commit()
    return user


@pytest.fixture
def auth_client(client: AsyncClient, user: User) -> AsyncClient:
    client.cookies.set(ACCESS_COOKIE, create_token(user.id, "access"))
    return client
