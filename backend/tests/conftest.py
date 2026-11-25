"""Test fixtures. Tests run against a real PostgreSQL database (default: corpmind_test),
because the app relies on Postgres-only features (tsvector, JSONB, enums).
"""
import importlib.util
import os
from pathlib import Path

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://corpmind:corpmind_dev@localhost:5432/corpmind_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-hs256-ok")
import tempfile  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="corpmind-test-")
os.environ["UPLOAD_DIR"] = os.path.join(_TMP, "uploads")
os.environ["CHROMA_DIR"] = os.path.join(_TMP, "chroma")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role  # noqa: E402
from app.services.auth_service import create_user  # noqa: E402
from app.services.embeddings import set_embedder  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.llm import set_llm  # noqa: E402
from app.services.reranker import set_reranker  # noqa: E402
from tests.fixtures import HashingEmbedder, ScriptedLLM  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
_seed_path = next((BACKEND / "alembic" / "versions").glob("*seed_categories_permissions.py"))
_spec = importlib.util.spec_from_file_location("seed", _seed_path)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)

PASSWORD = "Str0ngPassw0rd!"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """Reset to the freshly-migrated state before every test."""
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE feedback, messages, conversations, chunks, document_versions, documents, "
            "role_category_permissions, categories, refresh_tokens, audit_logs, users RESTART IDENTITY CASCADE"))
        for name, slug, desc, roles in seed.CATEGORIES:
            cid = conn.execute(text("INSERT INTO categories (name, slug, description) VALUES (:n,:s,:d) RETURNING id"),
                               {"n": name, "s": slug, "d": desc}).scalar_one()
            for r in roles:
                conn.execute(text("INSERT INTO role_category_permissions VALUES (CAST(:r AS user_role), :c)"),
                             {"r": r, "c": cid})
    set_embedder(HashingEmbedder())  # test-only embedder; the app itself uses sentence-transformers
    get_vector_store().reset()
    settings.ENABLE_RERANKER = False          # tests opt in with the `reranker` fixture
    settings.RELEVANCE_THRESHOLD = 0.20       # calibrated for the hashing test embedder
    set_reranker(None)
    set_llm(ScriptedLLM())                    # never call a real LLM from tests
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_user(email: str, role: Role = Role.EMPLOYEE):
    with SessionLocal() as db:
        u = create_user(db, email, email.split("@")[0].title(), PASSWORD, role=role)
        db.commit()
        return u


def login(client, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(client, email: str) -> dict:
    return {"Authorization": f"Bearer {login(client, email)['access_token']}"}


@pytest.fixture
def admin_headers(client):
    make_user("admin@corp.test", Role.ADMIN)
    return auth_headers(client, "admin@corp.test")


@pytest.fixture
def hr_headers(client):
    make_user("hr@corp.test", Role.HR)
    return auth_headers(client, "hr@corp.test")


@pytest.fixture
def employee_headers(client):
    make_user("emp@corp.test", Role.EMPLOYEE)
    return auth_headers(client, "emp@corp.test")


@pytest.fixture
def llm():
    model = ScriptedLLM()
    set_llm(model)
    return model
