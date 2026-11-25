"""FastAPI dependencies for authentication and role-based authorization.

Usage in a route:
    user: User = Depends(get_current_user)                   # any logged-in user
    admin: User = Depends(require_roles(Role.ADMIN))         # admin only
    staff: User = Depends(require_roles(Role.ADMIN, Role.HR))
"""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import ACCESS, TokenError, decode_token
from app.db.session import get_db
from app.models import Role, User

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        payload = decode_token(creds.credentials, ACCESS)
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError):
        raise _UNAUTHORIZED from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    # The role is always read from the DB, not trusted from the token, so a demotion takes effect immediately.
    return user


def require_roles(*roles: Role):
    allowed = set(roles)

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker
