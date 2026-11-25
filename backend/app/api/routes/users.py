"""/users/me and /categories: endpoints for the logged-in user."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import MeOut, PasswordChange, ProfileUpdate
from app.schemas.category import CategoryOut
from app.core.security import hash_password, verify_password
from app.services import audit
from app.services.auth_service import revoke_all_for_user
from app.services.permissions import allowed_categories

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=MeOut)
def read_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return MeOut(**{**_user_dict(user), "accessible_categories": [c.name for c in allowed_categories(db, user)]})


@router.patch("/users/me", response_model=MeOut)
def update_me(body: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(user)
    return MeOut(**{**_user_dict(user), "accessible_categories": [c.name for c in allowed_categories(db, user)]})


@router.post("/users/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(request: Request, body: PasswordChange, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    revoke_all_for_user(db, user.id)  # sign out every other session
    audit.record(db, "user.password_changed", user.id, request=request)
    db.commit()


@router.get("/categories", response_model=list[CategoryOut])
def my_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Categories the current user may read. Used for chat filters and upload forms."""
    return allowed_categories(db, user)


def _user_dict(user: User) -> dict:
    return {k: getattr(user, k) for k in
            ("id", "email", "full_name", "role", "department", "is_active", "created_at", "last_login_at")}
