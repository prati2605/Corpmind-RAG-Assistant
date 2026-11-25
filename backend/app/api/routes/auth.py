"""/auth: register, login, refresh, logout."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from app.services import audit
from app.services.auth_service import (
    AuthError, authenticate, create_user, issue_tokens, revoke_refresh_token, rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "corpmind_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    """The refresh token also goes in an httpOnly cookie, so browser JavaScript (and any injected script)
    can never read it. SameSite=Strict + a path limited to /auth blocks cross-site use."""
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, httponly=True,
        secure=settings.cookie_secure, samesite="strict", path=f"{settings.API_PREFIX}/auth")


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.API_PREFIX}/auth")


def _refresh_token_from(request: Request, body: RefreshRequest | None) -> str | None:
    return (body.refresh_token if body and body.refresh_token else None) or request.cookies.get(REFRESH_COOKIE)


def _raise(e: AuthError):
    headers = {"WWW-Authenticate": "Bearer"} if e.status_code == 401 else None
    raise HTTPException(status_code=e.status_code, detail=e.message, headers=headers)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """Self-registration. New accounts always get the Employee role; an admin can promote them later."""
    if not settings.ALLOW_SELF_REGISTRATION:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Self-registration is disabled. Ask an administrator.")
    domains = {d.lower().lstrip("@") for d in settings.REGISTRATION_EMAIL_DOMAINS}
    if domains and body.email.rsplit("@", 1)[-1] not in domains:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Register with your company email address.")
    try:
        user = create_user(db, body.email, body.full_name, body.password, department=body.department)
    except AuthError as e:
        _raise(e)
    audit.record(db, "user.register", user.id, "user", str(user.id), request=request)
    db.commit()
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(request: Request, response: Response, body: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = authenticate(db, body.email, body.password)
    except AuthError as e:
        audit.record(db, "auth.login_failed", details={"reason": e.message}, request=request)
        db.commit()
        _raise(e)
    tokens = issue_tokens(db, user)
    audit.record(db, "auth.login", user.id, request=request)
    db.commit()
    _set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def refresh(request: Request, response: Response, body: RefreshRequest | None = None, db: Session = Depends(get_db)):
    token = _refresh_token_from(request, body)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        _, tokens = rotate_refresh_token(db, token)
    except AuthError as e:
        _clear_refresh_cookie(response)
        db.commit()
        headers = {"WWW-Authenticate": "Bearer", "set-cookie": response.headers.get("set-cookie", "")}
        raise HTTPException(status_code=e.status_code, detail=e.message, headers=headers) from None
    db.commit()
    _set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, body: RefreshRequest | None = None,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = _refresh_token_from(request, body)
    if token:
        revoke_refresh_token(db, token, user.id)
    audit.record(db, "auth.logout", user.id, request=request)
    db.commit()
    _clear_refresh_cookie(response)
