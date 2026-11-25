"""Seed default document categories and role permissions.

Default access matrix (admins can always read every category, enforced in code):

    category                 employee   hr    admin
    General                     ✓        ✓      ✓
    HR Policies                 ✓        ✓      ✓
    IT & Security               ✓        ✓      ✓
    Finance & Expenses          ✓        ✓      ✓
    HR Confidential                      ✓      ✓
    Management & Strategy                       ✓

Admins can change this matrix at runtime from the admin panel.

Revision ID: a1c2e3f4d5b6
Revises: 6b3cdd1378d4
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c2e3f4d5b6"
down_revision: str | None = "6b3cdd1378d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = [
    ("General", "general", "Company-wide announcements, handbooks and general information", ["employee", "hr"]),
    ("HR Policies", "hr-policies", "Leave, attendance, conduct and benefits policies", ["employee", "hr"]),
    ("IT & Security", "it-security", "IT usage, information security and device policies", ["employee", "hr"]),
    ("Finance & Expenses", "finance", "Expense, reimbursement and travel policies", ["employee", "hr"]),
    ("HR Confidential", "hr-confidential", "Compensation bands, investigations, restricted HR material", ["hr"]),
    ("Management & Strategy", "management", "Board material, strategy and restricted plans", []),
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, slug, desc, roles in CATEGORIES:
        cat_id = conn.execute(
            sa.text("INSERT INTO categories (name, slug, description) VALUES (:n, :s, :d) "
                    "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id"),
            {"n": name, "s": slug, "d": desc},
        ).scalar_one()
        for role in roles:
            conn.execute(
                sa.text("INSERT INTO role_category_permissions (role, category_id) "
                        "VALUES (CAST(:r AS user_role), :c) ON CONFLICT DO NOTHING"),
                {"r": role, "c": cat_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    slugs = [c[1] for c in CATEGORIES]
    conn.execute(sa.text("DELETE FROM categories WHERE slug = ANY(:s) "
                         "AND id NOT IN (SELECT category_id FROM documents)"), {"s": slugs})
