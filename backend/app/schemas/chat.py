import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rag import CitationOut, SearchFilters


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = Field(default=None, description="Omit to start a new conversation")
    filters: SearchFilters = Field(default_factory=SearchFilters)


class StoredCitation(CitationOut):
    available: bool = True  # False if the document was deleted or the user lost access since


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[StoredCitation] = []
    confidence: float | None = None
    confidence_label: str | None = None
    grounded: bool | None = None
    mode: str | None = None
    latency_ms: int | None = None
    feedback: int | None = None          # the current user's rating: 1, -1 or None
    created_at: datetime


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    conversation_title: str
    user_message: MessageOut
    assistant_message: MessageOut


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message_preview: str | None


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class FeedbackIn(BaseModel):
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    message_id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime
