"""Category-based access control: the single source of truth for "what can this user read?".

Every place that reads document content (retrieval, citation lookup, document listing,
chunk preview) must call `allowed_category_ids` and filter by it. That is how access
control is enforced in the backend at retrieval time, not just hidden in the UI.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Role, RoleCategoryPermission, User


def allowed_category_ids(db: Session, user: User) -> set[int]:
    if not user.is_active:
        return set()
    if user.role == Role.ADMIN:
        return set(db.scalars(select(Category.id)))
    return set(db.scalars(select(RoleCategoryPermission.category_id).where(RoleCategoryPermission.role == user.role)))


def allowed_categories(db: Session, user: User) -> list[Category]:
    ids = allowed_category_ids(db, user)
    if not ids:
        return []
    return list(db.scalars(select(Category).where(Category.id.in_(ids)).order_by(Category.name)))


def can_access_category(db: Session, user: User, category_id: int) -> bool:
    return category_id in allowed_category_ids(db, user)


def set_category_roles(db: Session, category: Category, roles: list[Role]) -> None:
    """Replace the set of roles that can read a category. Admin access is implicit and never stored."""
    wanted = {r for r in roles if r != Role.ADMIN}
    current = {p.role: p for p in category.permissions}
    for role, perm in current.items():
        if role not in wanted:
            category.permissions.remove(perm)
    for role in wanted - current.keys():
        category.permissions.append(RoleCategoryPermission(role=role))
