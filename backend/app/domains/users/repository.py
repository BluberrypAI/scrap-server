import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users.models import SocialAccount, User


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_social_account(
    db: AsyncSession, provider: str, provider_subject: str
) -> SocialAccount | None:
    stmt = select(SocialAccount).where(
        SocialAccount.provider == provider,
        SocialAccount.provider_subject == provider_subject,
    )
    return await db.scalar(stmt)


async def get_provider(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    # Accounts are never merged, so each user has exactly one social account.
    stmt = select(SocialAccount.provider).where(SocialAccount.user_id == user_id).limit(1)
    return await db.scalar(stmt)


async def get_users_due_for_deletion(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    stmt = select(User.id).where(User.deletion_scheduled_at <= now)
    return list(await db.scalars(stmt))


async def delete_users(db: AsyncSession, user_ids: Sequence[uuid.UUID]) -> None:
    """Delete users and their social accounts. Rows in other domains are the caller's job."""
    await db.execute(
        delete(SocialAccount)
        .where(SocialAccount.user_id.in_(user_ids))
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(User).where(User.id.in_(user_ids)).execution_options(synchronize_session=False)
    )


async def create_user_with_social_account(
    db: AsyncSession,
    *,
    provider: str,
    provider_subject: str,
    email: str | None,
    name: str | None,
) -> User:
    user = User(email=email, name=name)
    db.add(user)
    await db.flush()
    db.add(
        SocialAccount(
            user_id=user.id, provider=provider, provider_subject=provider_subject, email=email
        )
    )
    return user
