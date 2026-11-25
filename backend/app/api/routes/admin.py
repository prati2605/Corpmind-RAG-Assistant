"""/admin: user management, category/permission management, audit log. Admin role only."""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import AuditLog, Category, Document, Role, User
from app.schemas.auth import AdminUserCreate, AdminUserUpdate, UserOut
from app.schemas.category import CategoryCreate, CategoryRolesUpdate, CategoryWithRoles
from app.services import audit
from app.services.auth_service import AuthError, create_user, revoke_all_for_user
from app.services.permissions import set_category_roles

router = APIRouter(prefix="/admin", tags=["admin"])
AdminUser = Depends(require_roles(Role.ADMIN))


# ---------- Users ----------

@router.get("/users", response_model=list[UserOut])
def list_users(q: str | None = Query(default=None, max_length=100), role: Role | None = None,
               limit: int = Query(default=50, le=200), offset: int = Query(default=0, ge=0),
               _: User = AdminUser, db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(User.email).like(like) | func.lower(User.full_name).like(like))
    if role:
        stmt = stmt.where(User.role == role)
    return list(db.scalars(stmt.limit(limit).offset(offset)))


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def admin_create_user(request: Request, body: AdminUserCreate, admin: User = AdminUser, db: Session = Depends(get_db)):
    try:
        user = create_user(db, body.email, body.full_name, body.password, role=body.role, department=body.department)
    except AuthError as e:
        raise HTTPException(e.status_code, e.message) from None
    audit.record(db, "admin.user_created", admin.id, "user", str(user.id), {"role": body.role.value}, request)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def admin_update_user(request: Request, user_id: uuid.UUID, body: AdminUserUpdate, admin: User = AdminUser,
                      db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("role") not in (None, Role.ADMIN) or changes.get("is_active") is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate your own account")
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("is_active") is False or "role" in changes:
        revoke_all_for_user(db, user.id)
    audit.record(db, "admin.user_updated", admin.id, "user", str(user.id),
                 {k: (v.value if isinstance(v, Role) else v) for k, v in changes.items()}, request)
    db.commit()
    db.refresh(user)
    return user


# ---------- Categories & permissions ----------

def _with_roles(c: Category) -> CategoryWithRoles:
    return CategoryWithRoles(id=c.id, name=c.name, slug=c.slug, description=c.description,
                             created_at=c.created_at, roles=sorted(p.role for p in c.permissions))


@router.get("/categories", response_model=list[CategoryWithRoles])
def list_categories(_: User = AdminUser, db: Session = Depends(get_db)):
    cats = db.scalars(select(Category).options(selectinload(Category.permissions)).order_by(Category.name))
    return [_with_roles(c) for c in cats]


@router.post("/categories", response_model=CategoryWithRoles, status_code=status.HTTP_201_CREATED)
def create_category(request: Request, body: CategoryCreate, admin: User = AdminUser, db: Session = Depends(get_db)):
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")
    if db.scalar(select(Category).where((Category.slug == slug) | (Category.name == body.name.strip()))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Category already exists")
    cat = Category(name=body.name.strip(), slug=slug, description=body.description)
    db.add(cat)
    set_category_roles(db, cat, body.roles)
    db.flush()
    audit.record(db, "admin.category_created", admin.id, "category", str(cat.id),
                 {"roles": [r.value for r in body.roles]}, request)
    db.commit()
    db.refresh(cat)
    return _with_roles(cat)


@router.put("/categories/{category_id}/roles", response_model=CategoryWithRoles)
def update_category_roles(request: Request, category_id: int, body: CategoryRolesUpdate, admin: User = AdminUser,
                          db: Session = Depends(get_db)):
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    set_category_roles(db, cat, body.roles)
    audit.record(db, "admin.category_permissions_changed", admin.id, "category", str(cat.id),
                 {"roles": [r.value for r in body.roles]}, request)
    db.commit()
    db.refresh(cat)
    return _with_roles(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(request: Request, category_id: int, admin: User = AdminUser, db: Session = Depends(get_db)):
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    if db.scalar(select(func.count()).select_from(Document).where(Document.category_id == category_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Category still contains documents; move or delete them first")
    db.delete(cat)
    audit.record(db, "admin.category_deleted", admin.id, "category", str(category_id), {"name": cat.name}, request)
    db.commit()


# ---------- Audit log ----------

class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: uuid.UUID | None
    action: str
    resource_type: str | None
    resource_id: str | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


@router.get("/audit-logs", response_model=list[AuditOut])
def list_audit_logs(action: str | None = Query(default=None, max_length=64), limit: int = Query(default=100, le=500),
                    offset: int = Query(default=0, ge=0), _: User = AdminUser, db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    return list(db.scalars(stmt.limit(limit).offset(offset)))
