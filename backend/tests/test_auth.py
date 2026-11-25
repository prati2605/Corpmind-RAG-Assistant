from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from tests.conftest import PASSWORD, auth_headers, login, make_user

API = "/api/v1"


def test_register_creates_employee_and_ignores_role_field(client):
    r = client.post(f"{API}/auth/register", json={
        "email": "New.User@Corp.test", "full_name": "New User", "password": PASSWORD, "role": "admin"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "employee"           # cannot self-assign admin
    assert body["email"] == "new.user@corp.test"  # normalised
    assert "hashed_password" not in body


def test_register_rejects_weak_password_and_duplicates(client):
    r = client.post(f"{API}/auth/register", json={"email": "a@corp.test", "full_name": "A B", "password": "short"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "password"
    make_user("dup@corp.test")
    r = client.post(f"{API}/auth/register", json={"email": "DUP@corp.test", "full_name": "Dup", "password": PASSWORD})
    assert r.status_code == 409


def test_login_success_and_failure_messages_are_identical(client):
    make_user("u@corp.test")
    tokens = login(client, "u@corp.test")
    assert tokens["token_type"] == "bearer" and tokens["refresh_token"]
    wrong_pw = client.post(f"{API}/auth/login", json={"email": "u@corp.test", "password": "WrongPass123"})
    no_user = client.post(f"{API}/auth/login", json={"email": "ghost@corp.test", "password": "WrongPass123"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # no user enumeration


def test_me_requires_valid_token(client):
    assert client.get(f"{API}/users/me").status_code == 401
    assert client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    expired = jwt.encode({"sub": "x", "type": "access", "jti": "j", "exp": datetime.now(UTC) - timedelta(minutes=1)},
                         settings.JWT_SECRET_KEY, algorithm="HS256")
    assert client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(client):
    make_user("u@corp.test")
    tokens = login(client, "u@corp.test")
    r = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    make_user("u@corp.test")
    t1 = login(client, "u@corp.test")
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()
    # Reusing the old (rotated) refresh token is rejected AND revokes the new one too.
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client):
    make_user("u@corp.test")
    t = login(client, "u@corp.test")
    h = {"Authorization": f"Bearer {t['access_token']}"}
    assert client.post(f"{API}/auth/logout", json={"refresh_token": t["refresh_token"]}, headers=h).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_change_password(client):
    make_user("u@corp.test")
    h = auth_headers(client, "u@corp.test")
    bad = client.post(f"{API}/users/me/password", headers=h,
                      json={"current_password": "nope", "new_password": "An0therGoodPass"})
    assert bad.status_code == 400
    ok = client.post(f"{API}/users/me/password", headers=h,
                     json={"current_password": PASSWORD, "new_password": "An0therGoodPass"})
    assert ok.status_code == 204
    login(client, "u@corp.test", "An0therGoodPass")


def test_profile_update(client, employee_headers):
    r = client.patch(f"{API}/users/me", headers=employee_headers, json={"full_name": "  Emp Loyee ", "department": "Ops"})
    assert r.status_code == 200
    assert r.json()["full_name"] == "Emp Loyee" and r.json()["department"] == "Ops"


def test_security_headers_present(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Request-ID" in r.headers


def test_browser_cookie_refresh_flow(client):
    make_user("cookie@corp.test")
    r = client.post(f"{API}/auth/login", json={"email": "cookie@corp.test", "password": PASSWORD})
    sc = r.headers["set-cookie"].lower()
    assert "corpmind_refresh=" in sc and "httponly" in sc and "samesite=strict" in sc and "path=/api/v1/auth" in sc
    # Refresh with only the cookie (TestClient keeps it); no body
    r2 = client.post(f"{API}/auth/refresh")
    assert r2.status_code == 200 and r2.json()["access_token"]
    # Logout clears it; a later cookie-only refresh fails
    h = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert client.post(f"{API}/auth/logout", headers=h).status_code == 204
    client.cookies.clear()
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_registration_domain_allowlist(client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_EMAIL_DOMAINS", ["northwind.com"])
    bad = client.post(f"{API}/auth/register", json={"email": "x@gmail.com", "full_name": "X Y", "password": PASSWORD})
    assert bad.status_code == 403 and "company email" in bad.json()["detail"]
    ok = client.post(f"{API}/auth/register", json={"email": "New@Northwind.com", "full_name": "X Y", "password": PASSWORD})
    assert ok.status_code == 201
