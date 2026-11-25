"""Guards the API surface: every endpoint needs sign-in except an explicit allowlist, and every
/admin endpoint is admin-only. Uses the same dependency inspection as the generated API docs."""
from app.main import app
from app.scripts.gen_api_docs import _access, _iter_routes, build

PUBLIC = {("GET", "/api/v1/health"), ("POST", "/api/v1/auth/register"),
          ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/refresh")}


def _routes():
    for path, route in _iter_routes(app.routes):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            yield method, path, _access(route)


def test_only_allowlisted_endpoints_are_public():
    public = {(m, p) for m, p, a in _routes() if a == "Public"}
    assert public == PUBLIC


def test_admin_endpoints_are_admin_only():
    admin = [(m, p, a) for m, p, a in _routes() if p.startswith("/api/v1/admin")]
    assert admin and all(a == "Admin" for _, _, a in admin), admin


def test_document_writes_need_manager_role():
    writes = [(m, p, a) for m, p, a in _routes() if p.startswith("/api/v1/documents") and m in {"POST", "DELETE"}]
    assert writes and all(a == "Admin, HR" for _, _, a in writes), writes


def test_api_docs_generate():
    md = build()
    assert "## Endpoint summary" in md and md.count("\n### `") >= 40
