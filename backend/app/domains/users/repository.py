import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users.models import User


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_identity(
    db: AsyncSession, provider: str, provider_subject: str
) -> User | None:
    stmt = select(User).where(User.provider == provider, User.provider_subject == provider_subject)
    return await db.scalar(stmt)


async def get_users_due_for_deletion(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    stmt = select(User.id).where(User.deletion_scheduled_at <= now)
    return list(await db.scalars(stmt))


async def delete_users(db: AsyncSession, user_ids: Sequence[uuid.UUID]) -> None:
    """Delete users. Rows in other domains are the caller's job."""
    await db.execute(
        delete(User).where(User.id.in_(user_ids)).execution_options(synchronize_session=False)
    )


async def create_user(
    db: AsyncSession,
    *,
    provider: str,
    provider_subject: str,
    email: str | None,
    name: str | None,
) -> User:
    user = User(provider=provider, provider_subject=provider_subject, email=email, name=name)
    db.add(user)
    await db.flush()
    return user
