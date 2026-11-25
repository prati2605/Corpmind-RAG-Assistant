"""/rag/query: stateless question answering (history passed in by the caller).

Used directly by the evaluation module and for API testing. Phase 4's conversation endpoints
call the same pipeline and add persistence (history, feedback).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models import User
from app.schemas.rag import QueryRequest, QueryResponse
from app.services.embeddings import EmbeddingModelError
from app.services.llm import LLMUnavailable
from app.services.rag.pipeline import answer_question, make_filters

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query", response_model=QueryResponse)
@limiter.limit(settings.RATE_LIMIT_CHAT)
def query(request: Request, body: QueryRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = body.filters
    try:
        result = answer_question(
            db, user, body.question, [h.model_dump() for h in body.history],
            make_filters(f.category_ids, f.document_ids, f.date_from, f.date_to))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    except LLMUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    except EmbeddingModelError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Document search is temporarily unavailable (embedding model not loaded)") from None
    return result.to_dict()
