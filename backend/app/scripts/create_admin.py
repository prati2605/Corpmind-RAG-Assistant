"""Create (or promote) the first administrator.

    python -m app.scripts.create_admin                       # uses FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD from .env
    python -m app.scripts.create_admin --email a@b.com       # prompts for the password

The password is read from the environment or prompted for, never passed on the command line
(command-line arguments end up in shell history and process lists).
"""
import argparse
import getpass
import os
import sys

from dotenv import load_dotenv

from app.core.config import BASE_DIR
from app.db.session import SessionLocal
from app.models import Role
from app.schemas.auth import _check_password_strength
from app.services.auth_service import create_user, get_user_by_email


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", default=os.getenv("FIRST_ADMIN_EMAIL"))
    parser.add_argument("--name", default="Administrator")
    args = parser.parse_args()
    if not args.email:
        sys.exit("Provide --email or set FIRST_ADMIN_EMAIL")

    with SessionLocal() as db:
        existing = get_user_by_email(db, args.email)
        if existing:
            existing.role, existing.is_active = Role.ADMIN, True
            db.commit()
            print(f"Promoted existing user {existing.email} to admin.")
            return
        password = os.getenv("FIRST_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
        try:
            _check_password_strength(password)
        except ValueError as e:
            sys.exit(str(e))
        user = create_user(db, args.email, args.name, password, role=Role.ADMIN)
        db.commit()
        print(f"Created admin {user.email}.")


if __name__ == "__main__":
    main()
