"""Upload validation: extension, size, and *actual* file content (magic bytes).

The extension alone is never trusted: a renamed .exe called policy.pdf is rejected because
its bytes don't start with %PDF. DOCX files are ZIP archives, so we also confirm the ZIP
contains word/document.xml and isn't a zip bomb.
"""
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from app.core.config import settings

MAX_DOCX_UNCOMPRESSED = 200 * 1024 * 1024  # 200 MB, guards against zip bombs
TEXT_SNIFF_BYTES = 64 * 1024


class UploadRejected(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class ValidatedFile:
    filename: str      # sanitized, display-safe
    extension: str     # ".pdf" | ".docx" | ".txt" | ".csv"
    data: bytes


def sanitize_filename(name: str | None) -> str:
    """Strip any path components and unsafe characters. The stored file never uses this
    name on disk (storage uses a UUID); this is only for display."""
    base = PurePath((name or "").replace("\\", "/")).name
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[^\w.\- ()&]", "_", base).strip(" .")
    return base[:200] or "document"


def _looks_like_text(data: bytes) -> bool:
    sample = data[:TEXT_SNIFF_BYTES]
    if b"\x00" in sample:
        return False
    for enc in ("utf-8-sig", "cp1252"):
        try:
            sample.decode(enc)
            return True
        except UnicodeDecodeError:
            # A multi-byte UTF-8 char may be cut at the sample boundary
            if enc == "utf-8-sig":
                try:
                    sample[:-3].decode(enc)
                    return True
                except UnicodeDecodeError:
                    continue
    return False


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise UploadRejected("File is not a valid Word document")
            if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise UploadRejected("Word document expands to an unsafe size")
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise UploadRejected("Macro-enabled documents are not accepted")
    except zipfile.BadZipFile:
        raise UploadRejected("File is not a valid Word document") from None


def validate_upload(filename: str | None, data: bytes) -> ValidatedFile:
    clean_name = sanitize_filename(filename)
    ext = PurePath(clean_name).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise UploadRejected(f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}")
    if len(data) == 0:
        raise UploadRejected("File is empty")
    if len(data) > settings.max_upload_bytes:
        raise UploadRejected(f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit")

    if ext == ".pdf":
        if not data.lstrip()[:5].startswith(b"%PDF-"):
            raise UploadRejected("File content is not a PDF")
    elif ext == ".docx":
        if not data.startswith(b"PK\x03\x04"):
            raise UploadRejected("File content is not a Word document")
        _check_docx(data)
    elif ext in (".txt", ".csv"):
        if not _looks_like_text(data):
            raise UploadRejected("File content is not plain text")
    return ValidatedFile(filename=clean_name, extension=ext, data=data)
