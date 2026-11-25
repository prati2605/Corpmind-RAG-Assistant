"""TEST-ONLY server for UI end-to-end checks without internet access or an LLM key.

    DATABASE_URL=...corpmind_e2e CHROMA_DIR=/tmp/e2e-chroma UPLOAD_DIR=/tmp/e2e-uploads \
        python -m tests.e2e_server

It runs the real app but swaps in the deterministic test embedder and the scripted LLM from
tests/fixtures.py, migrates a throwaway database, and seeds the sample corpus plus three users.
Never point it at a real database.
"""
import os

os.environ.setdefault("RELEVANCE_THRESHOLD", "0.2")
os.environ.setdefault("ENABLE_RERANKER", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

if "e2e" not in os.environ.get("DATABASE_URL", ""):
    raise SystemExit("Refusing to run: DATABASE_URL must point at a throwaway *_e2e database")

import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import BASE_DIR  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.services.auth_service import create_user, get_user_by_email  # noqa: E402
from app.services.embeddings import set_embedder  # noqa: E402
from app.services.llm import set_llm  # noqa: E402
from tests.fixtures import HashingEmbedder, ScriptedLLM  # noqa: E402

PASSWORD = os.environ.get("E2E_PASSWORD", "E2eDemoPass123")


def main():
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    command.upgrade(cfg, "head")
    set_embedder(HashingEmbedder())
    set_llm(ScriptedLLM())
    from app.scripts.seed_sample_data import seed_documents
    with SessionLocal() as db:
        for email, name, role in [("admin@northwind.local", "Asha Rao", Role.ADMIN),
                                  ("hr.demo@northwind.local", "Harini Iyer", Role.HR),
                                  ("employee.demo@northwind.local", "Esha Menon", Role.EMPLOYEE)]:
            if not get_user_by_email(db, email):
                create_user(db, email, name, PASSWORD, role=role, department="People Ops" if role != Role.EMPLOYEE else "Analytics")
        db.commit()
        admin = db.scalar(select(User).where(User.email == "admin@northwind.local"))
        print(seed_documents(db, admin, verbose=False))
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
