"""/chat: conversations, asking questions, feedback, suggested questions.

Every conversation and message is private to its owner. Any id belonging to someone else
returns 404 (not 403), so ids can't be probed.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models import Category, Document, DocumentVersion, Message, User
from app.schemas.chat import (AskRequest, AskResponse, ConversationDetail, ConversationRename, ConversationSummary,
                              FeedbackIn, FeedbackOut)
from app.services import chat_service as chat
from app.services.embeddings import EmbeddingModelError
from app.services.llm import LLMUnavailable
from app.services.permissions import allowed_category_ids
from app.services.rag.pipeline import make_filters

router = APIRouter(prefix="/chat", tags=["chat"])


def _raise(e: chat.ChatError):
    raise HTTPException(e.status_code, e.message)


@router.post("/ask", response_model=AskResponse)
@limiter.limit(settings.RATE_LIMIT_CHAT)
def ask(request: Request, body: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask a question. Starts a new conversation unless `conversation_id` is given."""
    f = body.filters
    try:
        conv, um, am = chat.ask(db, user, body.question, body.conversation_id,
                                make_filters(f.category_ids, f.document_ids, f.date_from, f.date_to))
        db.commit()
    except chat.ChatError as e:
        db.rollback()
        _raise(e)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    except LLMUnavailable as e:
        db.rollback()  # nothing is saved; the user can retry
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    except EmbeddingModelError:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Document search is temporarily unavailable (embedding model not loaded)") from None
    accessible = chat.accessible_document_ids(db, user, {c["document_id"] for c in am.citations or []})
    return {"conversation_id": conv.id, "conversation_title": conv.title,
            "user_message": chat.message_out(um, accessible, None),
            "assistant_message": chat.message_out(am, accessible, None)}


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(q: str | None = Query(default=None, max_length=200), limit: int = Query(default=30, le=100),
                       offset: int = Query(default=0, ge=0), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """The user's conversations, most recent first. `q` searches titles and message text."""
    return chat.list_conversations(db, user, q, limit, offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        conv = chat.get_own_conversation(db, user, conversation_id)
    except chat.ChatError as e:
        _raise(e)
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at, "updated_at": conv.updated_at,
            "messages": chat.conversation_messages(db, user, conv)}


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(conversation_id: uuid.UUID, body: ConversationRename, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    try:
        conv = chat.get_own_conversation(db, user, conversation_id)
    except chat.ChatError as e:
        _raise(e)
    conv.title = body.title.strip()
    db.commit()
    return next(c for c in chat.list_conversations(db, user, None, 100, 0) if c["id"] == conv.id)


@router.post("/conversations/{conversation_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
def clear_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """'Clear chat': remove all messages but keep the conversation."""
    try:
        conv = chat.get_own_conversation(db, user, conversation_id)
    except chat.ChatError as e:
        _raise(e)
    db.execute(delete(Message).where(Message.conversation_id == conv.id))
    db.commit()


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        conv = chat.get_own_conversation(db, user, conversation_id)
    except chat.ChatError as e:
        _raise(e)
    db.delete(conv)
    db.commit()


@router.put("/messages/{message_id}/feedback", response_model=FeedbackOut)
def give_feedback(message_id: uuid.UUID, body: FeedbackIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Thumbs up (1) / down (-1) on an answer, with an optional comment. Calling again changes it."""
    try:
        fb = chat.set_feedback(db, user, message_id, body.rating, body.comment)
    except chat.ChatError as e:
        db.rollback()
        _raise(e)
    db.commit()
    return {"message_id": fb.message_id, "rating": fb.rating, "comment": fb.comment, "created_at": fb.created_at}


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(message_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chat.remove_feedback(db, user, message_id)
    db.commit()


@router.get("/suggestions", response_model=list[str])
def suggestions(limit: int = Query(default=6, ge=1, le=12), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Suggested questions built from the documents this user can actually access (newest first)."""
    allowed = allowed_category_ids(db, user)
    if not allowed:
        return []
    rows = db.execute(
        select(Document.title, Category.name)
        .join(Category, Category.id == Document.category_id)
        .join(DocumentVersion, and_(DocumentVersion.document_id == Document.id, DocumentVersion.is_active.is_(True)))
        .where(Document.category_id.in_(allowed)).order_by(Document.updated_at.desc()).limit(20)).all()
    if not rows:
        return []
    templates = ["Summarize the {t}", "What are the key points of the {t}?", "What deadlines are mentioned in the {t}?"]
    out: list[str] = []
    for i, (title, _) in enumerate(rows):
        out.append(templates[i % len(templates)].format(t=title))
    by_cat: dict[str, list[str]] = {}
    for title, cat in rows:
        by_cat.setdefault(cat, []).append(title)
    pairs = [v[:2] for v in by_cat.values() if len(v) >= 2]
    if pairs:
        out.insert(1, f"Compare the {pairs[0][0]} and the {pairs[0][1]}")
    return list(dict.fromkeys(out))[:limit]
