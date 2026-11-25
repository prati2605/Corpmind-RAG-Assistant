"""Import every model so Base.metadata is complete (Alembic autogenerate relies on this)."""
from app.models.chat import Conversation, Feedback, Message
from app.models.document import Category, Chunk, Document, DocumentVersion, RoleCategoryPermission
from app.models.enums import DocumentStatus, MessageRole, Role
from app.models.user import AuditLog, RefreshToken, User

__all__ = [
    "AuditLog", "Category", "Chunk", "Conversation", "Document", "DocumentStatus", "DocumentVersion",
    "Feedback", "Message", "MessageRole", "RefreshToken", "Role", "RoleCategoryPermission", "User",
]
