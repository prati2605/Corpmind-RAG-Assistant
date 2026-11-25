"""/documents: upload, list, inspect, version management, delete, chunk preview, download.

Who can do what:
  - Everyone: list/view documents (and their text) only in categories they can read.
  - Admin + HR: upload, version, delete documents in categories they can read.
Every route re-checks category access in the backend; a hidden button is not security.
"""
import uuid
from datetime import date

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile,
                     status)
from fastapi.responses import FileResponse
from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models import Chunk, Document, DocumentStatus, DocumentVersion, Role, User
from app.schemas.document import (ChunkOut, DocumentDetail, DocumentOut, UploadResult, VersionAdminOut,
                                  VersionOut)
from app.services import audit
from app.services.document_service import (MANAGER_ROLES, DocumentError, activate_version, can_manage_category,
                                           create_upload, delete_document, delete_version, process_version)
from app.services.ingestion.validation import UploadRejected, validate_upload
from app.services.permissions import allowed_category_ids

router = APIRouter(prefix="/documents", tags=["documents"])
Manager = Depends(require_roles(Role.ADMIN, Role.HR))
MAX_FILES_PER_REQUEST = 20


# ---------------- helpers ----------------

async def _read_limited(upload: UploadFile) -> bytes:
    """Read at most MAX+1 bytes so an oversized upload can't exhaust memory."""
    limit = settings.max_upload_bytes
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise UploadRejected(f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit")
    return data


def _get_readable_doc(db: Session, user: User, document_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).options(selectinload(Document.versions), selectinload(Document.category))
                    .where(Document.id == document_id))
    if doc is None or doc.category_id not in allowed_category_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")  # same answer: no existence leak
    return doc


def _get_managed_doc(db: Session, user: User, document_id: uuid.UUID) -> Document:
    doc = _get_readable_doc(db, user, document_id)
    if not can_manage_category(db, user, doc.category_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    return doc


def _doc_out(doc: Document, detail: bool = False, admin_view: bool = False):
    versions = sorted(doc.versions, key=lambda v: v.version_number)
    active = next((v for v in versions if v.is_active), None)
    base = dict(
        id=doc.id, title=doc.title, description=doc.description, category_id=doc.category_id,
        category_name=doc.category.name, current_version=doc.current_version,
        status=versions[-1].status if versions else None,
        active_version=VersionOut.model_validate(active) if active else None,
        version_count=len(versions), injection_flagged=any(v.injection_flagged for v in versions),
        created_at=doc.created_at, updated_at=doc.updated_at,
    )
    if not detail:
        return DocumentOut(**base)
    vcls = VersionAdminOut if admin_view else VersionOut
    return DocumentDetail(**base, versions=[vcls.model_validate(v) for v in versions])


def _raise_doc_error(e: DocumentError):
    raise HTTPException(e.status_code, {"message": e.message, **e.extra} if e.extra else e.message)


# ---------------- upload ----------------

@router.post("", response_model=list[UploadResult], status_code=status.HTTP_207_MULTI_STATUS)
async def upload_documents(
    request: Request,
    background: BackgroundTasks,
    files: list[UploadFile] = File(..., description="One or more PDF, DOCX, TXT or CSV files"),
    category_id: int = Form(...),
    title: str | None = Form(default=None, max_length=255, description="Only used when uploading a single file"),
    description: str | None = Form(default=None, max_length=2000),
    effective_date: date | None = Form(default=None),
    user: User = Manager,
    db: Session = Depends(get_db),
):
    """Upload documents. Each file is validated independently and reported in the result list.
    Files whose title matches an existing document in the same category become a new version."""
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {MAX_FILES_PER_REQUEST} files per upload")
    if not can_manage_category(db, user, category_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Category not found or not permitted")

    results: list[UploadResult] = []
    to_process: list[uuid.UUID] = []
    for upload in files:
        name = upload.filename or "document"
        try:
            vf = validate_upload(name, await _read_limited(upload))
            outcome = create_upload(db, user, vf, category_id,
                                    title=title if len(files) == 1 else None,
                                    description=description, effective_date=effective_date)
            db.commit()
        except UploadRejected as e:
            results.append(UploadResult(filename=name, status="rejected", message=e.message))
            continue
        except DocumentError as e:
            db.rollback()
            st = "duplicate" if e.status_code == 409 else "rejected"
            results.append(UploadResult(filename=name, status=st, message=e.message,
                                        document_id=e.extra.get("document_id")))
            continue
        to_process.append(outcome.version.id)
        audit.record(db, "document.uploaded", user.id, "document", str(outcome.document.id),
                     {"version": outcome.version.version_number, "file_type": outcome.version.file_type}, request)
        db.commit()
        results.append(UploadResult(
            filename=vf.filename, status="accepted", document_id=outcome.document.id,
            version_id=outcome.version.id, version_number=outcome.version.version_number,
            new_version=outcome.new_version,
            message="Queued for processing" + (" as a new version" if outcome.new_version else "")))

    for vid in to_process:
        background.add_task(process_version, vid)
    return results


@router.post("/{document_id}/versions", response_model=UploadResult, status_code=status.HTTP_202_ACCEPTED)
async def upload_new_version(request: Request, document_id: uuid.UUID, background: BackgroundTasks,
                             file: UploadFile = File(...), effective_date: date | None = Form(default=None),
                             user: User = Manager, db: Session = Depends(get_db)):
    doc = _get_managed_doc(db, user, document_id)
    try:
        vf = validate_upload(file.filename, await _read_limited(file))
        outcome = create_upload(db, user, vf, doc.category_id, effective_date=effective_date, document_id=doc.id)
    except UploadRejected as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, e.message) from None
    except DocumentError as e:
        db.rollback()
        _raise_doc_error(e)
    audit.record(db, "document.version_uploaded", user.id, "document", str(doc.id),
                 {"version": outcome.version.version_number}, request)
    db.commit()
    background.add_task(process_version, outcome.version.id)
    return UploadResult(filename=vf.filename, status="accepted", document_id=doc.id, version_id=outcome.version.id,
                        version_number=outcome.version.version_number, new_version=True,
                        message="Queued for processing as a new version")


# ---------------- read ----------------

@router.get("", response_model=list[DocumentOut])
def list_documents(
    category_id: int | None = None,
    q: str | None = Query(default=None, max_length=200, description="Search in titles"),
    status_filter: DocumentStatus | None = Query(default=None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Documents in categories the user can read. Date filters use the document's effective date,
    falling back to its upload date. Employees only see documents that have a ready version."""
    allowed = allowed_category_ids(db, user)
    if category_id is not None:
        allowed &= {category_id}
    if not allowed:
        return []
    active = aliased(DocumentVersion)
    doc_date = func.coalesce(active.effective_date, cast(Document.created_at, Date))
    stmt = (select(Document)
            .outerjoin(active, and_(active.document_id == Document.id, active.is_active.is_(True)))
            .where(Document.category_id.in_(allowed))
            .options(selectinload(Document.versions), selectinload(Document.category))
            .order_by(Document.updated_at.desc()).limit(limit).offset(offset))
    if user.role not in MANAGER_ROLES:
        stmt = stmt.where(active.id.is_not(None))
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q.replace('%', '').replace('_', ' ')}%"))
    if date_from:
        stmt = stmt.where(doc_date >= date_from)
    if date_to:
        stmt = stmt.where(doc_date <= date_to)
    docs = list(db.scalars(stmt))
    out = [_doc_out(d) for d in docs]
    if status_filter:
        out = [d for d in out if d.status == status_filter]
    return out


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = _get_readable_doc(db, user, document_id)
    return _doc_out(doc, detail=True, admin_view=user.role in MANAGER_ROLES)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def list_chunks(document_id: uuid.UUID, page: int | None = Query(default=None, ge=1),
                limit: int = Query(default=50, le=200), offset: int = Query(default=0, ge=0),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Text of the active version (optionally one page). Used by the citation viewer."""
    doc = _get_readable_doc(db, user, document_id)
    stmt = (select(Chunk).where(Chunk.document_id == doc.id, Chunk.is_active.is_(True))
            .order_by(Chunk.chunk_index).limit(limit).offset(offset))
    if page is not None:
        stmt = stmt.where(Chunk.page_number == page)
    return list(db.scalars(stmt))


@router.get("/chunks/{chunk_id}", response_model=ChunkOut, tags=["documents"])
def get_chunk(chunk_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chunk = db.get(Chunk, chunk_id[:80])
    if chunk is None or chunk.category_id not in allowed_category_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return chunk


@router.get("/{document_id}/download")
def download(request: Request, document_id: uuid.UUID, version: int | None = None,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = _get_readable_doc(db, user, document_id)
    if version is None:
        v = next((x for x in doc.versions if x.is_active), None)
    else:
        v = next((x for x in doc.versions if x.version_number == version), None)
        if v is not None and not v.is_active and user.role not in MANAGER_ROLES:
            v = None  # only managers can fetch superseded versions
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    audit.record(db, "document.downloaded", user.id, "document", str(doc.id), {"version": v.version_number}, request)
    db.commit()
    media = {"pdf": "application/pdf", "txt": "text/plain; charset=utf-8", "csv": "text/csv; charset=utf-8",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[v.file_type]
    return FileResponse(v.storage_path, media_type=media, filename=v.original_filename,
                        content_disposition_type="inline" if v.file_type == "pdf" else "attachment")


# ---------------- manage ----------------

def _get_version(doc: Document, version_id: uuid.UUID) -> DocumentVersion:
    v = next((x for x in doc.versions if x.id == version_id), None)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return v


@router.post("/{document_id}/versions/{version_id}/activate", response_model=DocumentDetail)
def activate(request: Request, document_id: uuid.UUID, version_id: uuid.UUID, user: User = Manager,
             db: Session = Depends(get_db)):
    """Roll back (or forward) to a specific processed version."""
    doc = _get_managed_doc(db, user, document_id)
    v = _get_version(doc, version_id)
    if v.status != DocumentStatus.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only successfully processed versions can be activated")
    activate_version(db, v)
    audit.record(db, "document.version_activated", user.id, "document", str(doc.id), {"version": v.version_number}, request)
    db.commit()
    db.refresh(doc)
    return _doc_out(doc, detail=True, admin_view=True)


@router.post("/{document_id}/versions/{version_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
def reprocess(request: Request, document_id: uuid.UUID, version_id: uuid.UUID, background: BackgroundTasks,
              user: User = Manager, db: Session = Depends(get_db)):
    doc = _get_managed_doc(db, user, document_id)
    v = _get_version(doc, version_id)
    if v.status != DocumentStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed versions can be reprocessed")
    v.status = DocumentStatus.PENDING
    audit.record(db, "document.reprocess", user.id, "document", str(doc.id), {"version": v.version_number}, request)
    db.commit()
    background.add_task(process_version, v.id)
    return {"status": "queued"}


@router.delete("/{document_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_version(request: Request, document_id: uuid.UUID, version_id: uuid.UUID, user: User = Manager,
                   db: Session = Depends(get_db)):
    doc = _get_managed_doc(db, user, document_id)
    v = _get_version(doc, version_id)
    if v.status == DocumentStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Version is still processing")
    number = v.version_number
    doc_deleted = delete_version(db, v)
    audit.record(db, "document.version_deleted", user.id, "document", str(document_id),
                 {"version": number, "document_deleted": doc_deleted}, request)
    db.commit()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(request: Request, document_id: uuid.UUID, user: User = Manager, db: Session = Depends(get_db)):
    """Delete a document, all versions, stored files, Postgres chunks and Chroma vectors."""
    doc = _get_managed_doc(db, user, document_id)
    if any(v.status == DocumentStatus.PROCESSING for v in doc.versions):
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is still processing")
    title = doc.title
    delete_document(db, doc)
    audit.record(db, "document.deleted", user.id, "document", str(document_id), {"title": title}, request)
    db.commit()
