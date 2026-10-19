import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    pass


def create_token(user_id: uuid.UUID, token_type: TokenType) -> str:
    settings = get_settings()
    if token_type == "access":
        lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    else:
        lifetime = timedelta(days=settings.refresh_token_expire_days)
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "type": token_type, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != expected_type:
            raise InvalidTokenError("unexpected token type")
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
