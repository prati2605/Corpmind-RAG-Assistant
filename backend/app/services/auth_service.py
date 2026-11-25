"""Business logic for registration, login and token refresh/revocation."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    DUMMY_HASH, REFRESH, TokenError, create_access_token, create_refresh_token, decode_token,
    hash_password, verify_password,
)
from app.models import RefreshToken, Role, User


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def create_user(db: Session, email: str, full_name: str, password: str,
                role: Role = Role.EMPLOYEE, department: str | None = None) -> User:
    if get_user_by_email(db, email):
        raise AuthError("An account with this email already exists", 409)
    user = User(email=normalize_email(email), full_name=full_name, hashed_password=hash_password(password),
                role=role, department=department)
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, DUMMY_HASH)  # equalise timing so emails can't be enumerated
        raise AuthError("Invalid email or password")
    if not verify_password(password, user.hashed_password):
        raise AuthError("Invalid email or password")
    if not user.is_active:
        raise AuthError("Account is disabled", 403)
    user.last_login_at = datetime.now(UTC)
    return user


def issue_tokens(db: Session, user: User) -> dict:
    access = create_access_token(user.id, user.role.value)
    refresh, jti, exp = create_refresh_token(user.id)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=exp))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[User, dict]:
    """Exchange a refresh token for a new pair. The old refresh token is revoked (rotation).

    If a revoked token is presented again, that suggests theft, so every session of that user is revoked.
    """
    try:
        payload = decode_token(refresh_token, REFRESH)
    except TokenError as e:
        raise AuthError(str(e)) from e
    record = db.get(RefreshToken, payload["jti"])
    if record is None:
        raise AuthError("Invalid token")
    if record.revoked:
        revoke_all_for_user(db, record.user_id)
        db.commit()
        raise AuthError("Token has been revoked")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("Account is disabled", 403)
    record.revoked = True
    return user, issue_tokens(db, user)


def revoke_refresh_token(db: Session, refresh_token: str, user_id: uuid.UUID) -> None:
    try:
        payload = decode_token(refresh_token, REFRESH)
    except TokenError:
        return
    record = db.get(RefreshToken, payload["jti"])
    if record and record.user_id == user_id:
        record.revoked = True


def revoke_all_for_user(db: Session, user_id: uuid.UUID) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True))
