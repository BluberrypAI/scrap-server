import uuid

from sqlalchemy import select
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
