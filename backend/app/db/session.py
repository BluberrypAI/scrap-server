from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def build_engine(settings: Settings) -> AsyncEngine:
    """Same code path for SQLite (local), Docker PostgreSQL and Azure PostgreSQL."""
    if not settings.is_postgres:
        return create_async_engine(settings.database_url)

    connect_args: dict[str, Any] = {}
    if settings.db_ssl == "require":
        connect_args["ssl"] = "require"
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args=connect_args,
    )


engine = build_engine(get_settings())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """요청이 끝난 뒤 도는 작업(검토 실행 워커)이 자기 세션을 열 때 씀. 테스트에서 교체함."""
    return SessionLocal
