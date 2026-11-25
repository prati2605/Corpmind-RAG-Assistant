import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentStatus


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    original_filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    error_message: str | None
    page_count: int | None
    chunk_count: int | None
    is_active: bool
    effective_date: date | None
    injection_flagged: bool
    created_at: datetime
    processed_at: datetime | None


class VersionAdminOut(VersionOut):
    injection_findings: list | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    category_id: int
    category_name: str
    current_version: int
    status: DocumentStatus | None          # status of the newest version
    active_version: VersionOut | None
    version_count: int
    injection_flagged: bool
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    versions: list[VersionOut] | list[VersionAdminOut]


class UploadResult(BaseModel):
    filename: str
    status: str                 # "accepted" | "duplicate" | "rejected"
    message: str | None = None
    document_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    version_number: int | None = None
    new_version: bool = False


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    section: str | None
    text: str
