"""Cross-encoder reranking.

A bi-encoder (the embedding model) scores query and chunk separately, which is fast but coarse.
A cross-encoder reads the query and the chunk *together* and scores how well the chunk answers
the query, which is slower but much more accurate. So we retrieve ~20 candidates cheaply,
then rerank them with the cross-encoder and keep the best few.

Scores are passed through a sigmoid to get a 0..1 relevance probability, which is what the
relevance threshold and the confidence indicator use.
"""
import logging
import math
import threading
from typing import Protocol

from app.core.config import settings

log = logging.getLogger("corpmind.reranker")


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return a 0..1 relevance score per passage."""
        ...


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder

        log.info("Loading reranker %s", model_name)
        self._model = CrossEncoder(model_name, device="cpu", max_length=512)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        logits = self._model.predict([(query, p) for p in passages], batch_size=16, show_progress_bar=False)
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]


_reranker: Reranker | None = None
_failed = False
_lock = threading.Lock()


def get_reranker() -> Reranker | None:
    """Returns None if reranking is disabled or the model can't be loaded (retrieval still works)."""
    global _reranker, _failed
    if not settings.ENABLE_RERANKER or _failed:
        return _reranker if settings.ENABLE_RERANKER else None
    if _reranker is None:
        with _lock:
            if _reranker is None and not _failed:
                try:
                    _reranker = CrossEncoderReranker(settings.RERANKER_MODEL)
                except Exception:
                    _failed = True
                    log.warning("Reranker unavailable; continuing with hybrid scores only")
    return _reranker


def set_reranker(reranker: Reranker | None) -> None:
    global _reranker, _failed
    _reranker, _failed = reranker, False
