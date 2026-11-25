"""End-to-end ingestion through the API: Postgres + ChromaDB + files on disk."""
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Chunk, DocumentVersion
from app.services.vector_store import get_vector_store
from tests.conftest import auth_headers, make_user
from tests.fixtures import HOLIDAY_CSV, INJECTED_TEXT, LEAVE_POLICY_PAGES, make_docx, make_pdf
from app.models import Role

API = "/api/v1"


def _cat_id(client, headers, name):
    return next(c["id"] for c in client.get(f"{API}/categories", headers=headers).json() if c["name"] == name)


def _upload(client, headers, files, category_id, **form):
    data = {"category_id": str(category_id), **{k: str(v) for k, v in form.items()}}
    return client.post(f"{API}/documents", headers=headers, data=data,
                       files=[("files", (name, content, "application/octet-stream")) for name, content in files])


def _db_counts(document_id):
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id))
        active = db.scalar(select(func.count()).select_from(Chunk).where(
            Chunk.document_id == document_id, Chunk.is_active.is_(True)))
    return total, active


def test_multi_upload_processes_all_formats(client, admin_headers):
    cat = _cat_id(client, admin_headers, "HR Policies")
    r = _upload(client, admin_headers, [
        ("Leave_Policy.pdf", make_pdf(LEAVE_POLICY_PAGES)),
        ("Handbook.docx", make_docx([("Working Hours", "Office hours are 9:30 to 18:00.")])),
        ("Holidays 2026.csv", HOLIDAY_CSV.encode()),
        ("notes.txt", b"Payroll is processed on the last working day of each month."),
        ("virus.pdf", b"MZ not a pdf"),
    ], cat, effective_date="2026-01-01")
    assert r.status_code == 207, r.text
    results = {x["filename"]: x for x in r.json()}
    assert results["virus.pdf"]["status"] == "rejected"
    accepted = [x for x in r.json() if x["status"] == "accepted"]
    assert len(accepted) == 4

    # Background processing has completed by the time TestClient returns.
    docs = client.get(f"{API}/documents", headers=admin_headers).json()
    assert {d["title"] for d in docs} == {"Leave Policy", "Handbook", "Holidays 2026", "notes"}
    assert all(d["status"] == "ready" and d["active_version"]["chunk_count"] > 0 for d in docs)

    leave = next(d for d in docs if d["title"] == "Leave Policy")
    assert leave["active_version"]["page_count"] == 3
    chunks = client.get(f"{API}/documents/{leave['id']}/chunks", params={"page": 2}, headers=admin_headers).json()
    assert chunks and all(c["page_number"] == 2 for c in chunks)
    assert "carried forward" in " ".join(c["text"] for c in chunks)

    # Postgres chunks and Chroma vectors agree, and Chroma holds no document text.
    total, active = _db_counts(leave["id"])
    store = get_vector_store()
    assert store.count({"document_id": leave["id"]}) == total == active
    got = store.collection.get(where={"document_id": leave["id"]}, include=["documents", "metadatas"])
    assert all(d is None for d in got["documents"])
    assert {m["page"] for m in got["metadatas"]} == {1, 2, 3}


def test_duplicate_detection(client, admin_headers):
    cat = _cat_id(client, admin_headers, "HR Policies")
    pdf = make_pdf(LEAVE_POLICY_PAGES)
    _upload(client, admin_headers, [("Leave.pdf", pdf)], cat)
    r = _upload(client, admin_headers, [("Leave copy.pdf", pdf)], _cat_id(client, admin_headers, "General"))
    assert r.json()[0]["status"] == "duplicate"
    assert len(client.get(f"{API}/documents", headers=admin_headers).json()) == 1


def test_versioning_switches_active_vectors_and_rollback(client, admin_headers):
    cat = _cat_id(client, admin_headers, "HR Policies")
    v1 = _upload(client, admin_headers, [("Leave Policy.pdf", make_pdf(LEAVE_POLICY_PAGES))], cat).json()[0]
    new_pages = [LEAVE_POLICY_PAGES[0].replace("24 days", "26 days"), *LEAVE_POLICY_PAGES[1:]]
    # Same title in same category -> automatically a new version
    v2 = _upload(client, admin_headers, [("Leave Policy.pdf", make_pdf(new_pages))], cat).json()[0]
    assert v2["new_version"] and v2["version_number"] == 2 and v2["document_id"] == v1["document_id"]

    doc_id = v1["document_id"]
    detail = client.get(f"{API}/documents/{doc_id}", headers=admin_headers).json()
    assert detail["current_version"] == 2
    assert [v["is_active"] for v in detail["versions"]] == [False, True]

    store = get_vector_store()
    assert store.count({"$and": [{"version_id": v1["version_id"]}, {"is_active": True}]}) == 0
    assert store.count({"$and": [{"version_id": v2["version_id"]}, {"is_active": True}]}) > 0
    text = " ".join(c["text"] for c in client.get(f"{API}/documents/{doc_id}/chunks", headers=admin_headers).json())
    assert "26 days" in text and "24 days" not in text

    # Roll back to v1
    r = client.post(f"{API}/documents/{doc_id}/versions/{v1['version_id']}/activate", headers=admin_headers)
    assert r.status_code == 200 and r.json()["current_version"] == 1
    text = " ".join(c["text"] for c in client.get(f"{API}/documents/{doc_id}/chunks", headers=admin_headers).json())
    assert "24 days" in text

    # Deleting the active version falls back to the other ready version
    client.delete(f"{API}/documents/{doc_id}/versions/{v1['version_id']}", headers=admin_headers)
    detail = client.get(f"{API}/documents/{doc_id}", headers=admin_headers).json()
    assert detail["current_version"] == 2 and detail["version_count"] == 1
    assert store.count({"version_id": v1["version_id"]}) == 0


def test_delete_removes_vectors_rows_and_files(client, admin_headers):
    cat = _cat_id(client, admin_headers, "General")
    res = _upload(client, admin_headers, [("Notes.txt", b"The cafeteria opens at 8 AM on weekdays.")], cat).json()[0]
    with SessionLocal() as db:
        path = Path(db.get(DocumentVersion, res["version_id"]).storage_path)
    assert path.exists()
    assert client.delete(f"{API}/documents/{res['document_id']}", headers=admin_headers).status_code == 204
    assert not path.exists()
    assert _db_counts(res["document_id"]) == (0, 0)
    assert get_vector_store().count({"document_id": res["document_id"]}) == 0
    assert client.get(f"{API}/documents/{res['document_id']}", headers=admin_headers).status_code == 404


def test_injection_flagged_and_visible_to_managers_only(client, admin_headers, employee_headers):
    cat = _cat_id(client, admin_headers, "Finance & Expenses")
    res = _upload(client, admin_headers, [("Travel.txt", INJECTED_TEXT.encode())], cat).json()[0]
    admin_view = client.get(f"{API}/documents/{res['document_id']}", headers=admin_headers).json()
    assert admin_view["injection_flagged"]
    assert admin_view["versions"][0]["injection_findings"][0]["rule"] == "override_instructions"
    emp_view = client.get(f"{API}/documents/{res['document_id']}", headers=employee_headers).json()
    assert "injection_findings" not in emp_view["versions"][0]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.injection_flagged.is_(True))) >= 1


def test_access_control_on_document_endpoints(client, admin_headers, employee_headers, hr_headers):
    conf = _cat_id(client, admin_headers, "HR Confidential")
    mgmt = _cat_id(client, admin_headers, "Management & Strategy")
    hr_doc = _upload(client, admin_headers, [("Salary Bands.txt", b"Grade L3 salary band is 18 to 24 lakh.")], conf).json()[0]
    board = _upload(client, admin_headers, [("Board Plan.txt", b"Acquisition target for 2027 is confidential.")], mgmt).json()[0]

    # Employee: can't list, read, read chunks, download, or fetch a chunk by id
    assert client.get(f"{API}/documents", headers=employee_headers).json() == []
    for path in ("", "/chunks", "/download"):
        assert client.get(f"{API}/documents/{hr_doc['document_id']}{path}", headers=employee_headers).status_code == 404
    with SessionLocal() as db:
        chunk_id = db.scalar(select(Chunk.id).where(Chunk.document_id == hr_doc["document_id"]))
    assert client.get(f"{API}/documents/chunks/{chunk_id}", headers=employee_headers).status_code == 404
    assert client.get(f"{API}/documents/chunks/{chunk_id}", headers=hr_headers).status_code == 200

    # Employee can't upload at all; HR can't upload to or see Management
    assert _upload(client, employee_headers, [("x.txt", b"hello there")], _cat_id(client, employee_headers, "General")).status_code == 403
    assert _upload(client, hr_headers, [("x.txt", b"hello there")], mgmt).status_code == 403
    assert client.get(f"{API}/documents/{board['document_id']}", headers=hr_headers).status_code == 404
    assert client.delete(f"{API}/documents/{board['document_id']}", headers=hr_headers).status_code == 404
    assert {d["title"] for d in client.get(f"{API}/documents", headers=hr_headers).json()} == {"Salary Bands"}


def test_failed_processing_is_recorded_and_retryable(client, admin_headers):
    cat = _cat_id(client, admin_headers, "General")
    blank = make_pdf(["", ""], header="", footer=False)  # valid PDF, no text
    res = _upload(client, admin_headers, [("Scan.pdf", blank)], cat).json()[0]
    detail = client.get(f"{API}/documents/{res['document_id']}", headers=admin_headers).json()
    assert detail["status"] == "failed" and "scanned" in detail["versions"][0]["error_message"]
    # The same file can be re-uploaded (the failed version doesn't count as a duplicate)
    again = _upload(client, admin_headers, [("Scan.pdf", blank)], cat).json()[0]
    assert again["status"] == "accepted"


def test_filters_by_category_date_and_title(client, admin_headers):
    hr = _cat_id(client, admin_headers, "HR Policies")
    it = _cat_id(client, admin_headers, "IT & Security")
    _upload(client, admin_headers, [("Leave Policy.txt", b"Leave policy text for employees.")], hr, effective_date="2025-04-01")
    _upload(client, admin_headers, [("Password Policy.txt", b"Passwords must be rotated every 90 days.")], it, effective_date="2026-02-01")
    titles = lambda **p: {d["title"] for d in client.get(f"{API}/documents", headers=admin_headers, params=p).json()}
    assert titles(category_id=it) == {"Password Policy"}
    assert titles(date_from="2026-01-01") == {"Password Policy"}
    assert titles(date_to="2025-12-31") == {"Leave Policy"}
    assert titles(q="leave") == {"Leave Policy"}


def test_upload_audit_and_download(client, admin_headers):
    cat = _cat_id(client, admin_headers, "General")
    res = _upload(client, admin_headers, [("Guide.txt", b"Visitor badges are issued at reception.")], cat).json()[0]
    r = client.get(f"{API}/documents/{res['document_id']}/download", headers=admin_headers)
    assert r.status_code == 200 and r.content == b"Visitor badges are issued at reception."
    actions = {l["action"] for l in client.get(f"{API}/admin/audit-logs", headers=admin_headers).json()}
    assert {"document.uploaded", "document.downloaded"} <= actions


def test_interrupted_processing_recovered_at_startup(client, admin_headers):
    from app.models import DocumentStatus
    from app.services.document_service import recover_interrupted
    cat = _cat_id(client, admin_headers, "General")
    res = _upload(client, admin_headers, [("Memo.txt", b"Office closed on Friday for maintenance.")], cat).json()[0]
    with SessionLocal() as db:  # simulate a crash mid-processing
        db.get(DocumentVersion, res["version_id"]).status = DocumentStatus.PROCESSING
        db.commit()
        assert recover_interrupted(db) == 1
    v = client.get(f"{API}/documents/{res['document_id']}", headers=admin_headers).json()["versions"][0]
    assert v["status"] == "failed" and "interrupted" in v["error_message"]
    assert _db_counts(res["document_id"]) == (0, 0)
    assert get_vector_store().count({"document_id": res["document_id"]}) == 0
    r = client.post(f"{API}/documents/{res['document_id']}/versions/{res['version_id']}/reprocess", headers=admin_headers)
    assert r.status_code == 202
    assert client.get(f"{API}/documents/{res['document_id']}", headers=admin_headers).json()["status"] == "ready"


def test_embedding_model_failure_gives_actionable_message(client, admin_headers):
    from app.services.embeddings import EmbeddingModelError, set_embedder

    class Broken:
        model_name = "broken"
        def embed_documents(self, texts):
            raise EmbeddingModelError("Embedding model 'x' could not be loaded. Run download_models.")
        def embed_query(self, text):
            raise EmbeddingModelError("nope")

    set_embedder(Broken())
    cat = _cat_id(client, admin_headers, "General")
    res = _upload(client, admin_headers, [("Memo2.txt", b"Parking passes renew every January.")], cat).json()[0]
    v = client.get(f"{API}/documents/{res['document_id']}", headers=admin_headers).json()["versions"][0]
    assert v["status"] == "failed" and "download_models" in v["error_message"]
    assert _db_counts(res["document_id"]) == (0, 0)
