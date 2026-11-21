import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    pass


def token_lifetime(token_type: TokenType) -> timedelta:
    settings = get_settings()
    if token_type == "access":
        return timedelta(minutes=settings.access_token_expire_minutes)
    return timedelta(days=settings.refresh_token_expire_days)


def create_token(
    user_id: uuid.UUID, token_type: TokenType, token_id: uuid.UUID | None = None
) -> str:
    """token_id becomes the `jti` claim; refresh tokens carry their refresh_tokens row id."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + token_lifetime(token_type),
    }
    if token_id is not None:
        payload["jti"] = str(token_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str, expected_type: TokenType) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidTokenError("unexpected token type")
    return payload


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    payload = _decode(token, expected_type)
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def decode_refresh_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Return (user_id, token_id) of a refresh token."""
    payload = _decode(token, "refresh")
    try:
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["jti"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def decode_access_token(token: str) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Return the user and the issuing session, when the access token is session-bound."""
    payload = _decode(token, "access")
    try:
        session_id = uuid.UUID(payload["jti"]) if "jti" in payload else None
        return uuid.UUID(payload["sub"]), session_id
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
