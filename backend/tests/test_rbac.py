from app.db.session import SessionLocal
from app.models import Role, User
from app.services.permissions import allowed_category_ids
from tests.conftest import auth_headers, make_user

API = "/api/v1"


def _names(client, headers):
    return {c["name"] for c in client.get(f"{API}/categories", headers=headers).json()}


def test_default_category_access_matrix(client, admin_headers, hr_headers, employee_headers):
    base = {"General", "HR Policies", "IT & Security", "Finance & Expenses"}
    assert _names(client, employee_headers) == base
    assert _names(client, hr_headers) == base | {"HR Confidential"}
    assert _names(client, admin_headers) == base | {"HR Confidential", "Management & Strategy"}


def test_admin_endpoints_forbidden_for_non_admins(client, hr_headers, employee_headers):
    for h in (hr_headers, employee_headers):
        assert client.get(f"{API}/admin/users", headers=h).status_code == 403
        assert client.get(f"{API}/admin/categories", headers=h).status_code == 403
        assert client.post(f"{API}/admin/categories", headers=h, json={"name": "X"}).status_code == 403


def test_admin_changes_role_and_it_takes_effect_immediately(client, admin_headers):
    u = make_user("promote@corp.test")
    h = auth_headers(client, "promote@corp.test")
    assert "HR Confidential" not in _names(client, h)
    r = client.patch(f"{API}/admin/users/{u.id}", headers=admin_headers, json={"role": "hr"})
    assert r.status_code == 200 and r.json()["role"] == "hr"
    # Same (old) access token: role is read from the DB, so new permissions apply at once.
    assert "HR Confidential" in _names(client, h)


def test_deactivated_user_loses_access(client, admin_headers):
    u = make_user("bye@corp.test")
    h = auth_headers(client, "bye@corp.test")
    client.patch(f"{API}/admin/users/{u.id}", headers=admin_headers, json={"is_active": False})
    assert client.get(f"{API}/users/me", headers=h).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": "bye@corp.test", "password": "Str0ngPassw0rd!"})
    assert r.status_code == 403


def test_admin_cannot_demote_self(client, admin_headers):
    me = client.get(f"{API}/users/me", headers=admin_headers).json()
    r = client.patch(f"{API}/admin/users/{me['id']}", headers=admin_headers, json={"role": "employee"})
    assert r.status_code == 400


def test_category_create_and_permission_update(client, admin_headers, employee_headers):
    r = client.post(f"{API}/admin/categories", headers=admin_headers,
                    json={"name": "Legal", "description": "Contracts", "roles": ["hr"]})
    assert r.status_code == 201, r.text
    cat = r.json()
    assert cat["slug"] == "legal" and cat["roles"] == ["hr"]
    assert "Legal" not in _names(client, employee_headers)

    r = client.put(f"{API}/admin/categories/{cat['id']}/roles", headers=admin_headers,
                   json={"roles": ["hr", "employee", "admin"]})
    assert sorted(r.json()["roles"]) == ["employee", "hr"]  # admin is implicit, never stored
    assert "Legal" in _names(client, employee_headers)

    assert client.post(f"{API}/admin/categories", headers=admin_headers, json={"name": "Legal"}).status_code == 409
    assert client.delete(f"{API}/admin/categories/{cat['id']}", headers=admin_headers).status_code == 204


def test_permission_service_matches_api(client):
    make_user("svc@corp.test", Role.EMPLOYEE)
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="svc@corp.test").one()
        assert len(allowed_category_ids(db, u)) == 4
        u.is_active = False
        assert allowed_category_ids(db, u) == set()


def test_admin_user_listing_and_audit_log(client, admin_headers):
    make_user("a1@corp.test")
    r = client.get(f"{API}/admin/users", headers=admin_headers, params={"q": "a1"})
    assert [u["email"] for u in r.json()] == ["a1@corp.test"]
    logs = client.get(f"{API}/admin/audit-logs", headers=admin_headers, params={"action": "auth."}).json()
    assert any(l["action"] == "auth.login" for l in logs)
    # Audit details must never contain secrets
    assert all("password" not in str(l["details"]).lower() for l in logs)
