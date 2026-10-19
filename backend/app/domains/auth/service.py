from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.providers import extract_email
from app.domains.users import repository as user_repo
from app.domains.users.models import User


class MissingSubjectError(Exception):
    pass


async def login_or_register(db: AsyncSession, provider: str, userinfo: Mapping[str, Any]) -> User:
    """Find the user for a verified provider identity, creating one on first login."""
    subject = userinfo.get("sub")
    if not subject:
        raise MissingSubjectError

    account = await user_repo.get_social_account(db, provider, subject)
    if account:
        user = await user_repo.get_user(db, account.user_id)
        assert user is not None  # FK with cascade guarantees the user exists
        return user

    user = await user_repo.create_user_with_social_account(
        db,
        provider=provider,
        provider_subject=subject,
        email=extract_email(provider, dict(userinfo)),
        name=userinfo.get("name"),
    )
    await db.commit()
    return user
