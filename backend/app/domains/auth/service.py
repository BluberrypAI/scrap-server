import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    InvalidTokenError,
    create_token,
    decode_refresh_token,
    token_lifetime,
)
from app.domains.auth.models import RefreshToken
from app.domains.auth.providers import extract_email
from app.domains.users import repository as user_repo
from app.domains.users.models import User


class MissingSubjectError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


async def login_or_register(db: AsyncSession, provider: str, userinfo: Mapping[str, Any]) -> User:
    """Find the user for a verified provider identity, creating one on first login."""
    subject = userinfo.get("sub")
    if not subject:
        raise MissingSubjectError

    user = await user_repo.get_user_by_identity(db, provider, subject)
    if user:
        return user

    user = await user_repo.create_user(
        db,
        provider=provider,
        provider_subject=subject,
        email=extract_email(provider, dict(userinfo)),
        name=userinfo.get("name"),
    )
    await db.commit()
    return user


async def start_session(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Record a new refresh token and return it as a JWT."""
    token_id = uuid.uuid4()
    db.add(
        RefreshToken(
            id=token_id,
            user_id=user_id,
            expires_at=datetime.now(UTC) + token_lifetime("refresh"),
        )
    )
    await db.commit()
    return create_token(user_id, "refresh", token_id)


async def _revoke(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> bool:
    """Revoke one token if it is still valid. The conditional update makes rotation atomic."""
    result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == token_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    return result.rowcount == 1


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every valid refresh token of the user. The caller commits."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def delete_sessions_of_users(db: AsyncSession, user_ids: Sequence[uuid.UUID]) -> None:
    """Remove refresh token rows before users are purged. The caller commits."""
    await db.execute(
        delete(RefreshToken)
        .where(RefreshToken.user_id.in_(user_ids))
        .execution_options(synchronize_session=False)
    )


async def lock_guest_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialize rotation with link revocation on PostgreSQL. SQLite serializes writes."""
    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())


async def guest_session_active(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID | None
) -> bool:
    if session_id is None:
        return False
    active_id = await db.scalar(
        select(RefreshToken.id).where(
            RefreshToken.id == session_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    return active_id is not None


async def rotate_session(db: AsyncSession, refresh_token: str) -> tuple[User, str]:
    """Exchange a valid refresh token for a new one."""
    try:
        user_id, token_id = decode_refresh_token(refresh_token)
    except InvalidTokenError:
        raise InvalidRefreshTokenError from None

    user = await user_repo.get_user(db, user_id)
    if user is None or user.is_withdrawn:
        raise InvalidRefreshTokenError
    if user.is_guest:
        await lock_guest_sessions(db, user_id)

    if not await _revoke(db, user_id, token_id):
        known = await db.get(RefreshToken, token_id)
        if known is not None and known.user_id == user_id:
            # An already revoked token came back, so it was copied: end every session.
            await revoke_all_sessions(db, user_id)
            await db.commit()
        raise InvalidRefreshTokenError

    return user, await start_session(db, user_id)


async def end_session(db: AsyncSession, refresh_token: str | None) -> None:
    """Revoke the refresh token on logout. Invalid or missing tokens are ignored."""
    if not refresh_token:
        return
    try:
        user_id, token_id = decode_refresh_token(refresh_token)
    except InvalidTokenError:
        return
    await _revoke(db, user_id, token_id)
    await db.commit()
