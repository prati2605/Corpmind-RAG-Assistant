"""The RAG pipeline orchestrator: one function, `answer_question`, runs all nine steps.

 1. receive query           4. retrieve (hybrid, ACL-filtered)     7. build grounded prompt
 2. clean / condense / mode  5. relevance threshold                 8. generate with the LLM
 3. embed query              6. rerank                              9. validate citations -> answer

Short-circuits that never call the LLM:
- small talk ("hi", "thanks") -> canned greeting
- nothing relevant above the threshold -> the exact "couldn't find" message
"""
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User
from app.services.rag.generation import Citation, generate
from app.services.rag.prompt import FALLBACK_MESSAGE
from app.services.rag.query import (SMALL_TALK_REPLY, clean_query, condense_question, detect_mode, is_small_talk,
                                    match_documents)
from app.services.rag.retrieval import (RetrievalFilters, RetrievalResult, accessible_document_titles, retrieve,
                                        retrieve_document_for_summary, retrieve_for_comparison)

log = logging.getLogger("corpmind.rag")


@dataclass
class RAGAnswer:
    answer: str
    citations: list[Citation]
    grounded: bool
    mode: str
    standalone_question: str
    rewritten: bool
    confidence: float
    confidence_label: str
    retrieval: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)
    # The retrieved chunks, for the evaluation module only. Never serialised into API responses.
    context: list = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("context", None)
        return d


def _fallback(q: str, mode: str, rewritten: bool, r: RetrievalResult | None, timings: dict) -> RAGAnswer:
    return RAGAnswer(FALLBACK_MESSAGE, [], False, mode, q, rewritten, 0.0, "none",
                     _retrieval_meta(r), timings)


def _retrieval_meta(r: RetrievalResult | None) -> dict:
    if r is None:
        return {}
    return {"chunks_used": len(r.chunks), "candidates_considered": r.candidates_considered,
            "reranked": r.reranked, "truncated": r.truncated,
            "documents": sorted({c.title for c in r.chunks})}


def answer_question(db: Session, user: User, question: str, history: list[dict] | None = None,
                    filters: RetrievalFilters | None = None, generate_answer: bool = True) -> RAGAnswer:
    """generate_answer=False stops after retrieval (used by retrieval-only evaluation; needs no LLM)."""
    t0 = time.perf_counter()
    timings: dict[str, int] = {}
    filters = filters or RetrievalFilters()

    q = clean_query(question)
    if is_small_talk(q):
        return RAGAnswer(SMALL_TALK_REPLY, [], True, "small_talk", q, False, 0.0, "none", {},
                         {"total": int((time.perf_counter() - t0) * 1000)})

    standalone, rewritten = q, False
    if history:
        ts = time.perf_counter()
        standalone, rewritten = condense_question(q, history[-settings.CHAT_HISTORY_TURNS:])
        timings["condense"] = int((time.perf_counter() - ts) * 1000)

    # Which accessible documents does the question name? (Only the user's own documents are candidates.)
    if filters.document_ids:
        targets = list(filters.document_ids)
    else:
        targets = match_documents(standalone, accessible_document_titles(db, user, filters))
    mode = detect_mode(standalone, len(targets))

    ts = time.perf_counter()
    if mode == "summarize" and len(targets) >= 1:
        result = retrieve_document_for_summary(db, user, targets[0])
    elif mode == "compare" and len(targets) >= 2:
        result = retrieve_for_comparison(db, user, standalone, targets, filters)
    else:
        top_k = settings.RETRIEVAL_TOP_K + (2 if mode != "qa" else 0)
        result = retrieve(db, user, standalone, filters, top_k=top_k)
    timings["retrieval"] = int((time.perf_counter() - ts) * 1000)

    if not result.chunks:
        timings["total"] = int((time.perf_counter() - t0) * 1000)
        log.info("rag user=%s mode=%s result=no_context", user.id, mode)
        return _fallback(standalone, mode, rewritten, result, timings)

    if not generate_answer:
        timings["total"] = int((time.perf_counter() - t0) * 1000)
        return RAGAnswer("", [], True, mode, standalone, rewritten, result.confidence, result.confidence_label,
                         _retrieval_meta(result), timings, context=result.chunks)

    ts = time.perf_counter()
    gen = generate(standalone, result.chunks, mode, truncated=result.truncated)
    timings["generation"] = int((time.perf_counter() - ts) * 1000)
    timings["total"] = int((time.perf_counter() - t0) * 1000)

    log.info("rag user=%s mode=%s chunks=%d grounded=%s citations=%d conf=%.2f total_ms=%d",
             user.id, mode, len(result.chunks), gen.grounded, len(gen.citations), result.confidence, timings["total"])
    return RAGAnswer(
        answer=gen.text, citations=gen.citations, grounded=gen.grounded, mode=mode,
        standalone_question=standalone, rewritten=rewritten,
        confidence=result.confidence if gen.grounded else 0.0,
        confidence_label=result.confidence_label if gen.grounded else "none",
        retrieval=_retrieval_meta(result), latency_ms=timings, context=result.chunks)


def make_filters(category_ids: list[int] | None = None, document_ids: list[uuid.UUID] | None = None,
                 date_from=None, date_to=None) -> RetrievalFilters:
    return RetrievalFilters(category_ids=category_ids or None, document_ids=document_ids or None,
                            date_from=date_from, date_to=date_to)
