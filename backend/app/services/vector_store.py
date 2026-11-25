"""ChromaDB wrapper.

Each vector's id equals the `chunks.id` row in PostgreSQL. Metadata stored with each vector:
    document_id, version_id, category_id, page (-1 if none), is_active (bool), chunk_index

PostgreSQL is the source of truth. Chroma is an index that can be rebuilt from it.
Retrieval (Phase 3) filters Chroma by category_id + is_active, and then re-checks every
hit against PostgreSQL before using it, so even a stale Chroma entry can't leak content.
"""
import logging
import threading

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings

log = logging.getLogger("corpmind.vectors")

_BATCH = 500


class VectorStore:
    def __init__(self, path: str, collection: str):
        self._client = chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))
        self._col = self._client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}, embedding_function=None)

    @property
    def collection(self):
        return self._col

    def add(self, ids: list[str], embeddings: list[list[float]], metadatas: list[dict]) -> None:
        """Chunk text is deliberately NOT stored in Chroma: PostgreSQL holds the only copy,
        which keeps confidential text in one access-controlled place."""
        for i in range(0, len(ids), _BATCH):
            self._col.upsert(ids=ids[i:i + _BATCH], embeddings=embeddings[i:i + _BATCH],
                             metadatas=metadatas[i:i + _BATCH])

    def set_active(self, version_id: str, active: bool) -> int:
        res = self._col.get(where={"version_id": version_id}, include=["metadatas"])
        ids = res["ids"]
        if ids:
            metas = [{**m, "is_active": active} for m in res["metadatas"]]
            for i in range(0, len(ids), _BATCH):
                self._col.update(ids=ids[i:i + _BATCH], metadatas=metas[i:i + _BATCH])
        return len(ids)

    def delete_version(self, version_id: str) -> None:
        self._col.delete(where={"version_id": version_id})

    def delete_document(self, document_id: str) -> None:
        self._col.delete(where={"document_id": document_id})

    def count(self, where: dict | None = None) -> int:
        if where is None:
            return self._col.count()
        return len(self._col.get(where=where, include=[])["ids"])

    def query(self, embedding: list[float], k: int, where: dict) -> list[dict]:
        """Nearest neighbours. Returns [{id, metadata, similarity}] with similarity = 1 - cosine distance."""
        n = self._col.count()
        if n == 0:
            return []
        res = self._col.query(query_embeddings=[embedding], n_results=min(k, n), where=where,
                              include=["metadatas", "distances"])
        return [
            {"id": cid, "metadata": meta, "similarity": 1.0 - dist}
            for cid, meta, dist in zip(res["ids"][0], res["metadatas"][0], res["distances"][0])
        ]

    def reset(self) -> None:
        """Delete everything (tests / rebuild)."""
        name = self._col.name
        self._client.delete_collection(name)
        self._col = self._client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"},
                                                          embedding_function=None)


_store: VectorStore | None = None
_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                settings.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                _store = VectorStore(str(settings.CHROMA_DIR), settings.CHROMA_COLLECTION)
    return _store
