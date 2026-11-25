"""Audit trail for security-relevant events. Never put document text or secrets in `details`."""
import logging
import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

log = logging.getLogger("corpmind.audit")


def record(db: Session, action: str, user_id: uuid.UUID | None = None, resource_type: str | None = None,
           resource_id: str | None = None, details: dict | None = None, request: Request | None = None) -> None:
    ip = request.client.host if request and request.client else None
    db.add(AuditLog(user_id=user_id, action=action, resource_type=resource_type,
                    resource_id=resource_id, details=details, ip_address=ip))
    log.info("audit action=%s user=%s resource=%s:%s", action, user_id, resource_type, resource_id)
