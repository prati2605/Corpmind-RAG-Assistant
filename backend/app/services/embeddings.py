"""Embedding models (Hugging Face sentence-transformers).

`get_embedder()` returns a process-wide singleton. The model loads lazily on first use
(and downloads from Hugging Face on the very first run, then is cached in ~/.cache/huggingface).

Embeddings are L2-normalised, so cosine similarity = dot product. ChromaDB is configured
for cosine distance to match.

The `Embedder` protocol lets tests substitute a lightweight implementation without
touching the pipeline code.
"""
import logging
import threading
from typing import Protocol

from app.core.config import settings

log = logging.getLogger("corpmind.embeddings")


class EmbeddingModelError(Exception):
    """The embedding model could not be loaded (e.g. not downloaded yet and no internet)."""


class Embedder(Protocol):
    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    # Some models (E5, BGE) expect instruction prefixes for best retrieval quality.
    _PREFIXES = {
        "e5": ("passage: ", "query: "),
        "bge": ("", "Represent this sentence for searching relevant passages: "),
    }

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, deferred

        log.info("Loading embedding model %s", model_name)
        self.model_name = model_name
        try:
            self._model = SentenceTransformer(model_name, device="cpu")
        except Exception as e:
            raise EmbeddingModelError(
                f"Embedding model '{model_name}' could not be loaded. Check internet access or run "
                "`python -m app.scripts.download_models`, then reprocess.") from e
        lower = model_name.lower()
        self._doc_prefix, self._query_prefix = next(
            (v for k, v in self._PREFIXES.items() if k in lower), ("", ""))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode([self._doc_prefix + t for t in texts], batch_size=32,
                                  normalize_embeddings=True, show_progress_bar=False)
        return vecs.tolist()

    def embed_query(self, text: str) -> list[float]:
        vec = self._model.encode(self._query_prefix + text, normalize_embeddings=True, show_progress_bar=False)
        return vec.tolist()


_embedder: Embedder | None = None
_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                _embedder = SentenceTransformerEmbedder(settings.EMBEDDING_MODEL)
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Replace the singleton (used by tests and for warm-up at startup)."""
    global _embedder
    _embedder = embedder
