"""Conversations: persistence around the stateless RAG pipeline.

ask():
  1. load (or create) the user's conversation (ownership enforced: other users' ids look like 404)
  2. read the last CHAT_HISTORY_TURNS messages from the DB as history
  3. run the pipeline (history enables follow-up rewriting)
  4. store the user message and the assistant message (answer, citations, confidence, metadata)
  All in one transaction: if the LLM is down, nothing is saved and the user can simply retry.

Reading a conversation re-validates every stored citation against the user's *current* access,
so a citation to a document that was deleted, or moved to a category the user lost access to,
no longer shows its snippet.
"""
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Conversation, Document, Feedback, Message, MessageRole, User
from app.services.permissions import allowed_category_ids
from app.services.rag.pipeline import RAGAnswer, answer_question
from app.services.rag.retrieval import RetrievalFilters

TITLE_MAX = 80


class ChatError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def get_own_conversation(db: Session, user: User, conversation_id: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise ChatError("Conversation not found", 404)
    return conv


def make_title(question: str) -> str:
    t = re.sub(r"\s+", " ", question).strip()
    return t if len(t) <= TITLE_MAX else t[:TITLE_MAX].rsplit(" ", 1)[0] + "…"


def _history(db: Session, conv: Conversation) -> list[dict]:
    rows = db.scalars(select(Message).where(Message.conversation_id == conv.id)
                      .order_by(Message.created_at.desc()).limit(settings.CHAT_HISTORY_TURNS)).all()
    return [{"role": m.role.value, "content": m.content} for m in reversed(rows)]


def ask(db: Session, user: User, question: str, conversation_id: uuid.UUID | None,
        filters: RetrievalFilters) -> tuple[Conversation, Message, Message]:
    if conversation_id is not None:
        conv = get_own_conversation(db, user, conversation_id)
        history = _history(db, conv)
    else:
        conv = Conversation(user_id=user.id, title=make_title(question))
        db.add(conv)
        db.flush()
        history = []

    result: RAGAnswer = answer_question(db, user, question, history, filters)  # may raise -> caller rolls back

    user_msg = Message(conversation_id=conv.id, role=MessageRole.USER, content=question.strip())
    db.add(user_msg)
    db.flush()  # gives the user message an earlier created_at than the answer
    assistant_msg = Message(
        conversation_id=conv.id, role=MessageRole.ASSISTANT, content=result.answer,
        citations=[c.__dict__ for c in result.citations], confidence=result.confidence,
        latency_ms=result.latency_ms.get("total"),
        retrieval_meta={
            "grounded": result.grounded, "mode": result.mode, "confidence_label": result.confidence_label,
            "standalone_question": result.standalone_question, "rewritten": result.rewritten,
            "retrieval": result.retrieval, "latency_breakdown": result.latency_ms,
            "filters": {k: (v if not isinstance(v, list) else [str(x) for x in v])
                        for k, v in filters.__dict__.items() if v},
        })
    db.add(assistant_msg)
    conv.updated_at = func.now()
    db.flush()
    return conv, user_msg, assistant_msg


def message_out(m: Message, accessible_docs: set[str] | None, my_rating: int | None) -> dict:
    meta = m.retrieval_meta or {}
    citations = []
    for c in m.citations or []:
        ok = accessible_docs is not None and c.get("document_id") in accessible_docs
        citations.append({**c, "available": ok, **({} if ok else {"snippet": ""})})
    return {
        "id": m.id, "role": m.role.value, "content": m.content, "citations": citations,
        "confidence": m.confidence, "confidence_label": meta.get("confidence_label"),
        "grounded": meta.get("grounded"), "mode": meta.get("mode"), "latency_ms": m.latency_ms,
        "feedback": my_rating, "created_at": m.created_at,
    }


def accessible_document_ids(db: Session, user: User, doc_ids: set[str]) -> set[str]:
    """Which of these (cited) documents still exist and are readable by the user right now."""
    if not doc_ids:
        return set()
    allowed = allowed_category_ids(db, user)
    valid = []
    for d in doc_ids:
        try:
            valid.append(uuid.UUID(d))
        except ValueError:
            continue
    rows = db.scalars(select(Document.id).where(Document.id.in_(valid), Document.category_id.in_(allowed)))
    return {str(r) for r in rows}


def conversation_messages(db: Session, user: User, conv: Conversation) -> list[dict]:
    msgs = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)).all()
    cited = {c.get("document_id") for m in msgs for c in (m.citations or [])}
    accessible = accessible_document_ids(db, user, cited)
    ratings = dict(db.execute(select(Feedback.message_id, Feedback.rating).where(
        Feedback.user_id == user.id, Feedback.message_id.in_([m.id for m in msgs]))).all()) if msgs else {}
    return [message_out(m, accessible, ratings.get(m.id)) for m in msgs]


def list_conversations(db: Session, user: User, q: str | None, limit: int, offset: int) -> list[dict]:
    count_sq = (select(Message.conversation_id, func.count().label("n"))
                .group_by(Message.conversation_id).subquery())
    stmt = (select(Conversation, func.coalesce(count_sq.c.n, 0))
            .outerjoin(count_sq, count_sq.c.conversation_id == Conversation.id)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc()).limit(limit).offset(offset))
    if q:
        like = f"%{q.replace('%', '').replace('_', ' ')}%"
        matching = select(Message.conversation_id).where(Message.content.ilike(like))
        stmt = stmt.where(Conversation.title.ilike(like) | Conversation.id.in_(matching))
    rows = db.execute(stmt).all()
    out = []
    for conv, n in rows:
        last = db.scalar(select(Message.content).where(Message.conversation_id == conv.id)
                         .order_by(Message.created_at.desc()).limit(1))
        out.append({"id": conv.id, "title": conv.title, "created_at": conv.created_at, "updated_at": conv.updated_at,
                    "message_count": n, "last_message_preview": (last[:140] if last else None)})
    return out


def set_feedback(db: Session, user: User, message_id: uuid.UUID, rating: int, comment: str | None) -> Feedback:
    msg = db.get(Message, message_id)
    if msg is None or msg.conversation.user_id != user.id:
        raise ChatError("Message not found", 404)
    if msg.role != MessageRole.ASSISTANT:
        raise ChatError("Feedback can only be given on assistant answers", 400)
    fb = db.scalar(select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id))
    if fb is None:
        fb = Feedback(message_id=message_id, user_id=user.id, rating=rating, comment=comment)
        db.add(fb)
    else:
        fb.rating, fb.comment = rating, comment
    db.flush()
    return fb


def remove_feedback(db: Session, user: User, message_id: uuid.UUID) -> None:
    fb = db.scalar(select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id))
    if fb is not None:
        db.delete(fb)
