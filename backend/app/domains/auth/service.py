import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import passwords
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


PASSWORD_PROVIDER = "password"


def normalize_login_id(login_id: str) -> str:
    return login_id.strip().lower()


async def authenticate_password(db: AsyncSession, login_id: str, password: str) -> User | None:
    """아이디·비밀번호가 맞으면 사용자, 아니면 None. 탈퇴 여부는 호출자가 확인함."""
    user = await user_repo.get_user_by_identity(db, PASSWORD_PROVIDER, normalize_login_id(login_id))
    stored = user.password_hash if user else None
    # 없는 아이디도 해시 계산을 해서 응답 시간 차이를 줄임
    ok = passwords.verify_password(password, stored or passwords.DUMMY_HASH)
    return user if ok and stored else None


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


async def rotate_session(db: AsyncSession, refresh_token: str) -> tuple[uuid.UUID, str]:
    """Exchange a valid refresh token for a new one. Returns (user_id, new refresh token)."""
    try:
        user_id, token_id = decode_refresh_token(refresh_token)
    except InvalidTokenError:
        raise InvalidRefreshTokenError from None

    user = await user_repo.get_user(db, user_id)
    if user is None or user.is_withdrawn:
        raise InvalidRefreshTokenError

    if not await _revoke(db, user_id, token_id):
        known = await db.get(RefreshToken, token_id)
        if known is not None and known.user_id == user_id:
            # An already revoked token came back, so it was copied: end every session.
            await revoke_all_sessions(db, user_id)
            await db.commit()
        raise InvalidRefreshTokenError

    return user_id, await start_session(db, user_id)


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
