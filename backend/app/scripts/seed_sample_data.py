"""Load the fictional sample corpus and create demo users, for local demos and evaluation.

    python -m app.scripts.seed_sample_data                 # documents + demo users
    python -m app.scripts.seed_sample_data --no-users      # documents only

Documents in sample_docs/<category-slug>/ are uploaded into that category (the `versions/`
folder is skipped so you can demo versioning by uploading it yourself). Already-uploaded files are
skipped (duplicate detection). Demo users get the password from SAMPLE_USERS_PASSWORD, or you are
prompted; it is never printed.

Demo users:  hr.demo@northwind.local (HR)   employee.demo@northwind.local (Employee)
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

from app.core.config import BASE_DIR
from app.db.session import SessionLocal
from app.models import Category, Role, User
from app.schemas.auth import _check_password_strength
from app.services.auth_service import create_user, get_user_by_email
from app.services.document_service import DocumentError, create_upload, process_version
from app.services.ingestion.validation import UploadRejected, validate_upload

SAMPLE_DIR = BASE_DIR / "sample_docs"
DEMO_USERS = [("hr.demo@northwind.local", "Harini (HR demo)", Role.HR),
              ("employee.demo@northwind.local", "Esha (Employee demo)", Role.EMPLOYEE)]
EFFECTIVE_DATES = {"Leave Policy": "2026-01-01", "Remote Work Policy": "2026-02-01", "Travel and Expense Policy": "2025-10-01"}


def seed_documents(db, admin: User, sample_dir: Path = SAMPLE_DIR, verbose: bool = True) -> dict:
    from datetime import date

    cats = {c.slug: c for c in db.scalars(select(Category))}
    summary = {"uploaded": 0, "skipped": 0, "failed": 0}
    for folder in sorted(p for p in sample_dir.iterdir() if p.is_dir()):
        if folder.name == "versions" or folder.name.startswith(("_", ".")):
            continue
        cat = cats.get(folder.name)
        if cat is None:
            print(f"  ! no category with slug '{folder.name}', skipping folder")
            continue
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix.lower() not in {".pdf", ".docx", ".txt", ".csv"}:
                continue
            try:
                vf = validate_upload(f.name, f.read_bytes())
                eff = EFFECTIVE_DATES.get(f.stem)
                outcome = create_upload(db, admin, vf, cat.id, effective_date=date.fromisoformat(eff) if eff else None)
                db.commit()
            except (UploadRejected, DocumentError) as e:
                db.rollback()
                summary["skipped"] += 1
                if verbose:
                    print(f"  - {folder.name}/{f.name}: {getattr(e, 'message', e)}")
                continue
            process_version(outcome.version.id)  # synchronous here
            db.refresh(outcome.version)
            ok = outcome.version.status.value == "ready"
            summary["uploaded" if ok else "failed"] += 1
            if verbose:
                flag = " [prompt-injection flagged]" if outcome.version.injection_flagged else ""
                print(f"  {'✓' if ok else '✗'} {cat.name}: {f.name} -> {outcome.version.status.value}, "
                      f"{outcome.version.chunk_count or 0} chunks{flag}"
                      + ("" if ok else f" ({outcome.version.error_message})"))
    return summary


def seed_users(db, password: str) -> None:
    for email, name, role in DEMO_USERS:
        if get_user_by_email(db, email):
            print(f"  - user {email} exists")
            continue
        create_user(db, email, name, password, role=role)
        print(f"  ✓ user {email} ({role.value})")
    db.commit()


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-users", action="store_true")
    args = ap.parse_args()
    if not any(SAMPLE_DIR.glob("*/*.*")):
        sys.exit("No sample documents found. Run: python sample_docs/generate.py")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.role == Role.ADMIN, User.is_active.is_(True)))
        if admin is None:
            sys.exit("Create an admin first: python -m app.scripts.create_admin")
        if not args.no_users:
            pw = os.getenv("SAMPLE_USERS_PASSWORD") or getpass.getpass("Password for demo users: ")
            try:
                _check_password_strength(pw)
            except ValueError as e:
                sys.exit(str(e))
            print("Demo users:")
            seed_users(db, pw)
        print("Documents:")
        s = seed_documents(db, admin)
        print(f"Done: {s['uploaded']} uploaded, {s['skipped']} skipped, {s['failed']} failed.")


if __name__ == "__main__":
    main()
