"""Dashboard data.

/dashboard/stats      any user: their own usage + what they can access
/admin/analytics      admin: system-wide usage, answer quality and document health
/admin/feedback       admin: rated answers (with the question) for quality review
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import (Category, Chunk, Conversation, Document, DocumentStatus, DocumentVersion, Feedback, Message,
                        MessageRole, Role, User)
from app.services.permissions import allowed_category_ids

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats")
def my_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    allowed = allowed_category_ids(db, user)
    since = datetime.now(UTC) - timedelta(days=7)
    active_doc = and_(DocumentVersion.document_id == Document.id, DocumentVersion.is_active.is_(True))

    per_cat = db.execute(
        select(Category.id, Category.name, func.count(DocumentVersion.id))
        .outerjoin(Document, Document.category_id == Category.id)
        .outerjoin(DocumentVersion, active_doc)
        .where(Category.id.in_(allowed) if allowed else False)
        .group_by(Category.id, Category.name).order_by(Category.name)).all()
    my_q = select(func.count()).select_from(Message).join(Conversation).where(
        Conversation.user_id == user.id, Message.role == MessageRole.USER)
    recent_convs = db.execute(select(Conversation.id, Conversation.title, Conversation.updated_at)
                              .where(Conversation.user_id == user.id)
                              .order_by(Conversation.updated_at.desc()).limit(5)).all()
    recent_docs = db.execute(
        select(Document.id, Document.title, Category.name, DocumentVersion.processed_at)
        .join(DocumentVersion, active_doc).join(Category, Category.id == Document.category_id)
        .where(Document.category_id.in_(allowed) if allowed else False)
        .order_by(DocumentVersion.processed_at.desc().nulls_last()).limit(5)).all()

    return {
        "accessible_documents": sum(n for _, _, n in per_cat),
        "categories": [{"id": i, "name": n, "documents": c} for i, n, c in per_cat],
        "my_conversations": db.scalar(select(func.count()).select_from(Conversation)
                                      .where(Conversation.user_id == user.id)),
        "my_questions": db.scalar(my_q),
        "my_questions_last_7_days": db.scalar(my_q.where(Message.created_at >= since)),
        "recent_conversations": [{"id": i, "title": t, "updated_at": u} for i, t, u in recent_convs],
        "recent_documents": [{"id": i, "title": t, "category": c, "processed_at": p} for i, t, c, p in recent_docs],
    }


@router.get("/admin/analytics")
def analytics(days: int = Query(default=30, ge=1, le=365), _: User = Depends(require_roles(Role.ADMIN)),
              db: Session = Depends(get_db)):
    since = datetime.now(UTC) - timedelta(days=days)
    answers = (select(Message).where(Message.role == MessageRole.ASSISTANT, Message.created_at >= since,
                                     Message.retrieval_meta["mode"].astext != "small_talk").subquery())

    users_by_role = dict(db.execute(select(User.role, func.count()).where(User.is_active.is_(True))
                                    .group_by(User.role)).all())
    versions_by_status = dict(db.execute(select(DocumentVersion.status, func.count())
                                         .group_by(DocumentVersion.status)).all())
    total_answers, fallbacks, avg_lat, p95_lat, avg_conf = db.execute(select(
        func.count(),
        func.count().filter(answers.c.retrieval_meta["grounded"].astext == "false"),
        func.avg(answers.c.latency_ms),
        func.percentile_cont(0.95).within_group(answers.c.latency_ms),
        func.avg(answers.c.confidence).filter(answers.c.retrieval_meta["grounded"].astext == "true"),
    )).one()
    pos, neg = db.execute(select(
        func.count().filter(Feedback.rating == 1), func.count().filter(Feedback.rating == -1))
        .where(Feedback.created_at >= since)).one()

    per_day = db.execute(
        select(func.date_trunc("day", Message.created_at).label("d"), func.count())
        .where(Message.role == MessageRole.USER, Message.created_at >= since)
        .group_by(text("d")).order_by(text("d"))).all()
    mode_col = answers.c.retrieval_meta["mode"].astext.label("mode")
    modes = dict(db.execute(select(mode_col, func.count()).group_by(text("mode"))).all())
    top_docs = db.execute(text("""
        SELECT c->>'document_id' AS id, c->>'title' AS title, count(*) AS n
        FROM messages m, jsonb_array_elements(m.citations) c
        WHERE m.role = 'assistant' AND m.created_at >= :since
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 8"""), {"since": since}).all()
    active_users = db.scalar(select(func.count(func.distinct(Conversation.user_id)))
                             .join(Message, Message.conversation_id == Conversation.id)
                             .where(Message.created_at >= since))

    return {
        "period_days": days,
        "users": {"total_active": sum(users_by_role.values()),
                  "by_role": {r.value: users_by_role.get(r, 0) for r in Role},
                  "active_in_period": active_users},
        "documents": {
            "total": db.scalar(select(func.count()).select_from(Document)),
            "versions_by_status": {s.value: versions_by_status.get(s, 0) for s in DocumentStatus},
            "active_chunks": db.scalar(select(func.count()).select_from(Chunk).where(Chunk.is_active.is_(True))),
            "injection_flagged": db.scalar(select(func.count()).select_from(DocumentVersion)
                                           .where(DocumentVersion.injection_flagged.is_(True))),
            "storage_bytes": db.scalar(select(func.coalesce(func.sum(DocumentVersion.file_size), 0))),
        },
        "questions": {
            "answered": total_answers,
            "not_found_rate": round(fallbacks / total_answers, 3) if total_answers else None,
            "avg_confidence": round(float(avg_conf), 3) if avg_conf is not None else None,
            "modes": modes,
            "per_day": [{"date": d.date().isoformat(), "count": n} for d, n in per_day],
        },
        "latency_ms": {"avg": round(float(avg_lat)) if avg_lat else None,
                       "p95": round(float(p95_lat)) if p95_lat else None},
        "feedback": {"positive": pos, "negative": neg,
                     "satisfaction": round(pos / (pos + neg), 3) if (pos + neg) else None},
        "top_cited_documents": [{"document_id": i, "title": t, "citations": n} for i, t, n in top_docs],
    }


@router.get("/admin/feedback")
def feedback_review(rating: int | None = Query(default=None, description="1 or -1"),
                    limit: int = Query(default=50, le=200), offset: int = Query(default=0, ge=0),
                    _: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    """Rated answers with the question that produced them, for improving documents and settings."""
    q_msg = aliased(Message)
    question = (select(q_msg.content).where(q_msg.conversation_id == Message.conversation_id,
                                            q_msg.role == MessageRole.USER, q_msg.created_at < Message.created_at)
                .order_by(q_msg.created_at.desc()).limit(1).correlate(Message).scalar_subquery())
    stmt = (select(Feedback, Message, User.email, question.label("question"))
            .join(Message, Message.id == Feedback.message_id).join(User, User.id == Feedback.user_id)
            .order_by(Feedback.created_at.desc()).limit(limit).offset(offset))
    if rating in (1, -1):
        stmt = stmt.where(Feedback.rating == rating)
    out = []
    for fb, msg, email, qtext in db.execute(stmt):
        meta = msg.retrieval_meta or {}
        out.append({"id": fb.id, "rating": fb.rating, "comment": fb.comment, "created_at": fb.created_at,
                    "user_email": email, "question": qtext, "answer": msg.content,
                    "grounded": meta.get("grounded"), "confidence": msg.confidence,
                    "cited_documents": sorted({c.get("title") for c in (msg.citations or [])})})
    return out

