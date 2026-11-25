"""Steps 3-6 of the pipeline: hybrid, access-controlled retrieval with threshold and reranking.

    query --embed--> ChromaDB nearest neighbours  ┐   both filtered by the user's allowed
    query --------> Postgres full-text search     ┘   categories + active versions
                         │
             Reciprocal Rank Fusion (RRF)
                         │
     Postgres re-check: load chunk text only if still active AND in an allowed category
     (+ date / document filters). Text never comes from Chroma, so a stale vector can't leak.
                         │
     cosine similarity for every candidate  ->  cross-encoder rerank (if available)
                         │
     relevance threshold  ->  top-k  ->  confidence score

Why hybrid? Vector search understands meaning ("time off" ≈ "leave"); keyword search nails exact
terms that embeddings blur: policy codes, names, numbers ("form HR-27", "Section 4.2").
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Date, and_, bindparam, cast, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, Document, DocumentStatus, DocumentVersion, User
from app.services.embeddings import get_embedder
from app.services.permissions import allowed_category_ids
from app.services.reranker import get_reranker
from app.services.vector_store import get_vector_store

log = logging.getLogger("corpmind.retrieval")

RRF_K = 60


@dataclass
class RetrievalFilters:
    category_ids: list[int] | None = None
    document_ids: list[uuid.UUID] | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: uuid.UUID
    title: str
    category_id: int
    page: int | None
    section: str | None
    chunk_index: int
    text: str
    injection_flagged: bool
    version_number: int
    effective_date: date | None
    similarity: float = 0.0       # cosine(query, chunk)
    keyword_coverage: float = 0.0 # share of the query's search terms found in the chunk
    rrf: float = 0.0              # fused rank score
    relevance: float = 0.0        # the score the threshold is applied to (reranker prob, or cosine)
    sources: list[str] = field(default_factory=list)  # which retrievers found it: "vector", "keyword"


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    confidence: float
    confidence_label: str          # "high" | "medium" | "low" | "none"
    reranked: bool
    candidates_considered: int
    truncated: bool = False        # summarize: document longer than the context budget


# ---------------- scoring helpers ----------------

def _confidence(chunks: list[RetrievedChunk], reranked: bool) -> tuple[float, str]:
    if not chunks:
        return 0.0, "none"
    rels = sorted((c.relevance for c in chunks), reverse=True)
    top = rels[:3]
    score = round(0.6 * rels[0] + 0.4 * (sum(top) / len(top)), 3)
    high, medium = (settings.CONFIDENCE_HIGH_RERANK, settings.CONFIDENCE_MEDIUM_RERANK) if reranked else (
        settings.CONFIDENCE_HIGH_COSINE, settings.CONFIDENCE_MEDIUM_COSINE)
    label = "high" if score >= high else "medium" if score >= medium else "low"
    return score, label


def _cosine_map(ids: list[str], qvec: list[float]) -> dict[str, float]:
    if not ids:
        return {}
    got = get_vector_store().collection.get(ids=ids, include=["embeddings"])
    out = {}
    for cid, emb in zip(got["ids"], got["embeddings"]):
        out[cid] = float(sum(a * b for a, b in zip(qvec, emb)))  # vectors are normalised
    return out


# ---------------- the two retrievers ----------------

def _vector_search(qvec: list[float], allowed: list[int], doc_ids: list[uuid.UUID] | None, n: int) -> list[str]:
    conds: list[dict] = [{"is_active": True}, {"category_id": {"$in": allowed}}]
    if doc_ids:
        conds.append({"document_id": {"$in": [str(d) for d in doc_ids]}})
    hits = get_vector_store().query(qvec, n, where={"$and": conds})
    return [h["id"] for h in hits]


_KEYWORD_SQL = text("""
    SELECT c.id
    FROM chunks c
    JOIN document_versions v ON v.id = c.version_id
    WHERE c.tsv @@ to_tsquery('english', :tsq)
      AND c.is_active AND v.is_active
      AND c.category_id = ANY(:cats)
      AND (CAST(:docs AS uuid[]) IS NULL OR c.document_id = ANY(CAST(:docs AS uuid[])))
    ORDER BY ts_rank_cd(c.tsv, to_tsquery('english', :tsq), 32) DESC
    LIMIT :n
""").bindparams(bindparam("cats"), bindparam("docs"))


def _keyword_search(db: Session, query: str, allowed: list[int], doc_ids: list[uuid.UUID] | None, n: int) -> list[str]:
    # plainto_tsquery stems words and drops stopwords; we then OR the terms together so a
    # natural-language question matches chunks containing *any* of its key terms (ranked by how many).
    tsq = db.scalar(text("SELECT replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')"), {"q": query})
    if not tsq:
        return []
    return list(db.scalars(_KEYWORD_SQL, {"tsq": tsq, "cats": allowed, "n": n,
                                          "docs": [str(d) for d in doc_ids] if doc_ids else None}))


# ---------------- Postgres re-check ----------------

def _load_authorized(db: Session, ids: list[str], allowed: list[int], filters: RetrievalFilters) -> dict[str, RetrievedChunk]:
    """Load chunk text from Postgres, re-applying every access and freshness rule.
    Anything Chroma returned that fails these checks is silently dropped."""
    if not ids:
        return {}
    doc_date = func.coalesce(DocumentVersion.effective_date, cast(Document.created_at, Date))
    stmt = (select(Chunk, Document.title, DocumentVersion.version_number, DocumentVersion.effective_date,
                   func.tsvector_to_array(Chunk.tsv))
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(ids), Chunk.is_active.is_(True), Chunk.category_id.in_(allowed),
                   Document.category_id == Chunk.category_id,
                   DocumentVersion.is_active.is_(True), DocumentVersion.status == DocumentStatus.READY))
    if filters.document_ids:
        stmt = stmt.where(Chunk.document_id.in_(filters.document_ids))
    if filters.date_from:
        stmt = stmt.where(doc_date >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(doc_date <= filters.date_to)
    out = {}
    for chunk, title, vno, eff, lexemes in db.execute(stmt):
        out[chunk.id] = RetrievedChunk(
            chunk_id=chunk.id, document_id=chunk.document_id, title=title, category_id=chunk.category_id,
            page=chunk.page_number, section=chunk.section, chunk_index=chunk.chunk_index, text=chunk.text,
            injection_flagged=chunk.injection_flagged, version_number=vno, effective_date=eff)
        out[chunk.id]._lexemes = set(lexemes or [])
    return out


def _query_lexemes(db: Session, query: str) -> set[str]:
    return set(db.scalar(text("SELECT tsvector_to_array(to_tsvector('english', :q))"), {"q": query}) or [])


def effective_categories(db: Session, user: User, filters: RetrievalFilters) -> list[int]:
    allowed = allowed_category_ids(db, user)
    if filters.category_ids:
        allowed &= set(filters.category_ids)   # a filter can only narrow access, never widen it
    return sorted(allowed)


# ---------------- main entry points ----------------

def retrieve(db: Session, user: User, query: str, filters: RetrievalFilters | None = None,
             top_k: int | None = None, threshold_scale: float = 1.0,
             max_per_document: int | None = None) -> RetrievalResult:
    filters = filters or RetrievalFilters()
    top_k = top_k or settings.RETRIEVAL_TOP_K
    max_per_document = max_per_document or settings.MAX_CHUNKS_PER_DOCUMENT
    allowed = effective_categories(db, user, filters)
    if not allowed:
        return RetrievalResult([], 0.0, "none", False, 0)

    n = settings.RETRIEVAL_CANDIDATES * (3 if (filters.date_from or filters.date_to) else 1)
    qvec = get_embedder().embed_query(query)
    vec_ids = _vector_search(qvec, allowed, filters.document_ids, n)
    kw_ids = _keyword_search(db, query, allowed, filters.document_ids, n)

    # Reciprocal Rank Fusion: score = Σ 1/(60 + rank). Rewards chunks ranked well by either retriever,
    # and chunks found by both, without needing the two score scales to be comparable.
    fused: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    for name, ids in (("vector", vec_ids), ("keyword", kw_ids)):
        for rank, cid in enumerate(ids, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
            sources.setdefault(cid, []).append(name)

    ordered = sorted(fused, key=fused.get, reverse=True)[:settings.RETRIEVAL_CANDIDATES]
    loaded = _load_authorized(db, ordered, allowed, filters)
    sims = _cosine_map(list(loaded), qvec)
    q_lex = _query_lexemes(db, query)
    candidates = []
    for cid in ordered:
        if cid in loaded:
            c = loaded[cid]
            c.rrf, c.similarity, c.sources = fused[cid], sims.get(cid, 0.0), sources[cid]
            c.keyword_coverage = len(q_lex & c._lexemes) / len(q_lex) if q_lex else 0.0
            candidates.append(c)

    reranker = get_reranker()
    if reranker is not None and candidates:
        for c, s in zip(candidates, reranker.score(query, [c.text for c in candidates])):
            c.relevance = s
        threshold = settings.RERANK_THRESHOLD * threshold_scale
        candidates.sort(key=lambda c: c.relevance, reverse=True)
    else:
        # Without a cross-encoder, relevance is the better of semantic similarity and keyword coverage.
        # Coverage is squared so a chunk must contain most of the query's key terms to pass on keywords
        # alone. This lets exact identifiers ("FIN-12", "HR-27") through even when their embedding
        # similarity to a long paragraph is low, while one or two incidental shared words don't.
        for c in candidates:
            c.relevance = max(c.similarity, 0.9 * c.keyword_coverage ** 2)
        threshold = settings.RELEVANCE_THRESHOLD * threshold_scale
        candidates.sort(key=lambda c: (c.rrf, c.similarity), reverse=True)

    kept, per_doc = [], {}
    for c in candidates:
        if c.relevance < threshold:
            continue
        if per_doc.get(c.document_id, 0) >= max_per_document:
            continue
        per_doc[c.document_id] = per_doc.get(c.document_id, 0) + 1
        kept.append(c)
        if len(kept) >= top_k:
            break

    conf, label = _confidence(kept, reranker is not None)
    log.info("retrieve user=%s cats=%d vec=%d kw=%d candidates=%d kept=%d reranked=%s conf=%.2f",
             user.id, len(allowed), len(vec_ids), len(kw_ids), len(candidates), len(kept), reranker is not None, conf)
    return RetrievalResult(kept, conf, label, reranker is not None, len(candidates))


def retrieve_document_for_summary(db: Session, user: User, document_id: uuid.UUID) -> RetrievalResult:
    """Summaries need the whole document in order, not the 'most similar' pieces.
    Loads the active version's chunks in reading order, up to the context budget."""
    allowed = effective_categories(db, user, RetrievalFilters())
    rows = db.scalars(select(Chunk.id).where(Chunk.document_id == document_id, Chunk.is_active.is_(True))
                      .order_by(Chunk.chunk_index)).all()
    loaded = _load_authorized(db, list(rows), allowed, RetrievalFilters(document_ids=[document_id]))
    chunks, used, truncated = [], 0, False
    for cid in rows:
        c = loaded.get(cid)
        if c is None:
            continue
        if used + len(c.text) > settings.SUMMARY_MAX_CHARS and chunks:
            truncated = True
            break
        c.relevance = 1.0  # the user explicitly asked for this document
        chunks.append(c)
        used += len(c.text)
    conf, label = (1.0, "high") if chunks else (0.0, "none")
    return RetrievalResult(chunks, conf, label, False, len(rows), truncated=truncated)


def retrieve_for_comparison(db: Session, user: User, query: str, document_ids: list[uuid.UUID],
                            filters: RetrievalFilters | None = None) -> RetrievalResult:
    """Retrieve from each named document separately so one long document can't crowd out the other."""
    filters = filters or RetrievalFilters()
    merged: list[RetrievedChunk] = []
    reranked = False
    considered = 0
    for doc_id in document_ids[:settings.COMPARE_MAX_DOCUMENTS]:
        f = RetrievalFilters(category_ids=filters.category_ids, document_ids=[doc_id],
                             date_from=filters.date_from, date_to=filters.date_to)
        # Documents were named explicitly, so the bar is lowered: we want each side's best evidence.
        r = retrieve(db, user, query, f, top_k=settings.COMPARE_CHUNKS_PER_DOCUMENT, threshold_scale=0.5,
                     max_per_document=settings.COMPARE_CHUNKS_PER_DOCUMENT)
        merged.extend(r.chunks)
        reranked = reranked or r.reranked
        considered += r.candidates_considered
    conf, label = _confidence(merged, reranked)
    return RetrievalResult(merged, conf, label, reranked, considered)


def accessible_document_titles(db: Session, user: User, filters: RetrievalFilters | None = None) -> list[tuple]:
    allowed = effective_categories(db, user, filters or RetrievalFilters())
    if not allowed:
        return []
    return list(db.execute(
        select(Document.id, Document.title)
        .join(DocumentVersion, and_(DocumentVersion.document_id == Document.id, DocumentVersion.is_active.is_(True)))
        .where(Document.category_id.in_(allowed))).all())


__all__ = ["RetrievalFilters", "RetrievedChunk", "RetrievalResult", "retrieve", "retrieve_document_for_summary",
           "retrieve_for_comparison", "accessible_document_titles"]
