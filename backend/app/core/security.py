"""Password hashing (Argon2id) and JWT creation/verification.

Two token types:
- access  (short-lived, sent as `Authorization: Bearer ...` on every request)
- refresh (longer-lived, used only at /auth/refresh; its jti is tracked in the DB so it can be revoked)
"""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


# A real hash of a random string, used to keep login timing constant when the email doesn't exist.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class TokenError(Exception):
    pass


def _encode(sub: str, token_type: str, expires: timedelta, extra: dict | None = None) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    exp = now + expires
    jti = uuid.uuid4().hex
    payload = {"sub": sub, "type": token_type, "iat": now, "exp": exp, "jti": jti, **(extra or {})}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM), jti, exp


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    token, _, _ = _encode(str(user_id), ACCESS, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), {"role": role})
    return token


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at)."""
    return _encode(str(user_id), REFRESH, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                             options={"require": ["exp", "sub", "type", "jti"]})
    except jwt.ExpiredSignatureError as e:
        raise TokenError("Token expired") from e
    except jwt.PyJWTError as e:
        raise TokenError("Invalid token") from e
    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    return payload
