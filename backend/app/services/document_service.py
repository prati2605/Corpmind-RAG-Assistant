"""Document lifecycle: upload, dedup, versioning, processing, activation, deletion.

Upload flow (request thread, fast):
    validate -> SHA-256 hash -> duplicate check -> save file under a random name
    -> create Document (or a new DocumentVersion of an existing one) with status=pending

Processing flow (background task, slow):
    parse -> clean -> injection scan -> chunk -> embed -> write chunks to Postgres + vectors
    to Chroma (inactive) -> activate (flip this version on, previous version off) -> status=ready

Writing everything as inactive first and flipping at the end means users never see a
half-ingested document, and the previous version keeps serving answers until the new one is ready.
"""
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Category, Chunk, Document, DocumentStatus, DocumentVersion, Role, User
from app.services.embeddings import EmbeddingModelError, get_embedder
from app.services.ingestion.chunking import chunk_segments
from app.services.ingestion.cleaning import clean_segments
from app.services.ingestion.injection_scan import scan_text
from app.services.ingestion.parsers import ParseError, parse_file
from app.services.ingestion.validation import ValidatedFile
from app.services.permissions import can_access_category
from app.services.vector_store import get_vector_store

log = logging.getLogger("corpmind.documents")

MANAGER_ROLES = {Role.ADMIN, Role.HR}


class DocumentError(Exception):
    def __init__(self, message: str, status_code: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.message, self.status_code, self.extra = message, status_code, extra or {}


@dataclass
class UploadOutcome:
    document: Document
    version: DocumentVersion
    new_version: bool  # True if this upload added a version to an existing document


# ---------------- Permissions ----------------

def can_manage_category(db: Session, user: User, category_id: int) -> bool:
    """Admins manage all categories; HR manages documents in categories HR can read."""
    return user.role in MANAGER_ROLES and can_access_category(db, user, category_id)


# ---------------- Storage ----------------

def _storage_path(version_id: uuid.UUID, ext: str) -> Path:
    # Random name: the user-supplied filename never touches the filesystem.
    return settings.UPLOAD_DIR / f"{version_id.hex}{ext}"


def _remove_file(path: str | None) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove stored file for cleanup")


# ---------------- Upload ----------------

def create_upload(db: Session, user: User, vf: ValidatedFile, category_id: int, title: str | None = None,
                  description: str | None = None, effective_date: date | None = None,
                  document_id: uuid.UUID | None = None) -> UploadOutcome:
    content_hash = hashlib.sha256(vf.data).hexdigest()

    existing = db.scalar(select(DocumentVersion).where(DocumentVersion.content_hash == content_hash))
    if existing is not None:
        if existing.status == DocumentStatus.FAILED:
            # A failed earlier attempt shouldn't block a retry of the same file.
            delete_version(db, existing)  # also removes its document if it was the only version
            db.flush()
        else:
            raise DocumentError("This exact file has already been uploaded", 409, {
                "document_id": str(existing.document_id), "version": existing.version_number,
                "title": existing.document.title})

    if document_id is not None:
        doc = db.get(Document, document_id)
        if doc is None:
            raise DocumentError("Document not found", 404)
        if not can_manage_category(db, user, doc.category_id):
            raise DocumentError("Document not found", 404)  # don't reveal existence
    else:
        if db.get(Category, category_id) is None or not can_manage_category(db, user, category_id):
            raise DocumentError("Category not found or not permitted", 403)
        doc_title = (title or Path(vf.filename).stem.replace("_", " ")).strip()[:255]
        # Same title in the same category = a new version of that document.
        doc = db.scalar(select(Document).where(Document.title == doc_title, Document.category_id == category_id))
        if doc is None:
            doc = Document(title=doc_title, category_id=category_id, description=description, uploaded_by=user.id)
            db.add(doc)
            db.flush()

    is_new_version = doc.versions != [] if document_id is None else True
    next_no = (db.scalar(select(func.max(DocumentVersion.version_number))
                         .where(DocumentVersion.document_id == doc.id)) or 0) + 1
    version_id = uuid.uuid4()
    path = _storage_path(version_id, vf.extension)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(vf.data)

    version = DocumentVersion(
        id=version_id, document_id=doc.id, version_number=next_no, original_filename=vf.filename,
        file_type=vf.extension.lstrip("."), file_size=len(vf.data), content_hash=content_hash,
        storage_path=str(path), status=DocumentStatus.PENDING, effective_date=effective_date, uploaded_by=user.id)
    db.add(version)
    if description and document_id is None and not doc.description:
        doc.description = description
    try:
        db.flush()
    except Exception:
        _remove_file(str(path))
        raise
    return UploadOutcome(document=doc, version=version, new_version=is_new_version)


# ---------------- Processing (background) ----------------

def recover_interrupted(db: Session) -> int:
    """Called at startup. Background tasks die with the process, so any version still
    pending/processing was interrupted: mark it failed so an admin can reprocess or delete it."""
    stuck = db.scalars(select(DocumentVersion).where(
        DocumentVersion.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]))).all()
    for v in stuck:
        db.execute(Chunk.__table__.delete().where(Chunk.version_id == v.id))
        get_vector_store().delete_version(str(v.id))
        v.status = DocumentStatus.FAILED
        v.error_message = "Processing was interrupted by a server restart. Use Reprocess to try again."
    db.commit()
    if stuck:
        log.warning("Marked %d interrupted document version(s) as failed", len(stuck))
    return len(stuck)


def process_version(version_id: uuid.UUID) -> None:
    """Background task entry point. Uses its own DB session; never raises."""
    with SessionLocal() as db:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            return
        version.status = DocumentStatus.PROCESSING
        version.error_message = None
        db.commit()
        try:
            _ingest(db, version)
            activate_version(db, version)
            version.status = DocumentStatus.READY
            version.processed_at = datetime.now(UTC)
            db.commit()
            log.info("Processed version=%s chunks=%s pages=%s flagged=%s", version.id,
                     version.chunk_count, version.page_count, version.injection_flagged)
        except Exception as e:  # record the failure, clean partial state
            db.rollback()
            version = db.get(DocumentVersion, version_id)
            if version is None:
                return
            db.execute(Chunk.__table__.delete().where(Chunk.version_id == version.id))
            try:
                get_vector_store().delete_version(str(version.id))
            except Exception:
                log.exception("Vector cleanup failed for version=%s", version.id)
            version.status = DocumentStatus.FAILED
            version.error_message = e.message if isinstance(e, DocumentError) else (
                str(e) if isinstance(e, (ParseError, EmbeddingModelError))
                else "Processing failed due to an internal error")
            if not isinstance(e, (ParseError, DocumentError)):
                log.exception("Processing failed for version=%s", version.id)
            db.commit()


def _ingest(db: Session, version: DocumentVersion) -> None:
    data = Path(version.storage_path).read_bytes()
    parsed = parse_file("." + version.file_type, data)
    segments = clean_segments(parsed.segments)
    chunks = chunk_segments(segments)
    if not chunks:
        raise DocumentError("No usable text found in document")

    doc = version.document
    findings, rows = [], []
    for c in chunks:
        hits = scan_text(c.text)
        findings.extend({"rule": h.rule, "page": c.page, "excerpt": h.excerpt} for h in hits)
        rows.append(Chunk(
            id=f"{version.id.hex}-{c.index:05d}", version_id=version.id, document_id=doc.id,
            category_id=doc.category_id, chunk_index=c.index, page_number=c.page,
            section=(c.section or None), text=c.text, is_active=False, injection_flagged=bool(hits)))

    embeddings = get_embedder().embed_documents([r.text for r in rows])
    db.add_all(rows)
    db.flush()
    get_vector_store().add(
        ids=[r.id for r in rows],
        embeddings=embeddings,
        metadatas=[{
            "document_id": str(doc.id), "version_id": str(version.id), "category_id": doc.category_id,
            "page": r.page_number if r.page_number is not None else -1, "chunk_index": r.chunk_index,
            "is_active": False,
        } for r in rows],
    )
    version.page_count = parsed.page_count
    version.chunk_count = len(rows)
    version.injection_flagged = bool(findings)
    version.injection_findings = findings[:50] or None


# ---------------- Activation / versions ----------------

def activate_version(db: Session, version: DocumentVersion) -> None:
    """Make `version` the one used for retrieval and deactivate all others of the same document."""
    doc = db.scalar(select(Document).where(Document.id == version.document_id).with_for_update())
    store = get_vector_store()
    others = db.scalars(select(DocumentVersion).where(
        DocumentVersion.document_id == doc.id, DocumentVersion.id != version.id,
        DocumentVersion.is_active.is_(True))).all()
    for other in others:
        other.is_active = False
        db.execute(update(Chunk).where(Chunk.version_id == other.id).values(is_active=False))
        store.set_active(str(other.id), False)
    version.is_active = True
    db.execute(update(Chunk).where(Chunk.version_id == version.id).values(is_active=True))
    store.set_active(str(version.id), True)
    doc.current_version = version.version_number


def _delete_version_rows(db: Session, version: DocumentVersion) -> None:
    get_vector_store().delete_version(str(version.id))
    _remove_file(version.storage_path)
    db.delete(version)  # chunks cascade


def delete_version(db: Session, version: DocumentVersion) -> bool:
    """Delete one version. If it was active, fall back to the newest remaining READY version.
    Returns True if the whole document was deleted because no versions remain."""
    doc = version.document
    was_active = version.is_active
    _delete_version_rows(db, version)
    db.flush()
    db.refresh(doc)
    if not doc.versions:
        db.delete(doc)
        return True
    if was_active:
        fallback = next((v for v in sorted(doc.versions, key=lambda v: v.version_number, reverse=True)
                         if v.status == DocumentStatus.READY), None)
        if fallback is not None:
            activate_version(db, fallback)
        else:
            doc.current_version = 0
    return False


def delete_document(db: Session, doc: Document) -> None:
    get_vector_store().delete_document(str(doc.id))
    for v in doc.versions:
        _remove_file(v.storage_path)
    db.delete(doc)
