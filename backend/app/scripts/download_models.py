"""Download and smoke-test the embedding and reranker models once, ahead of first use.

    python -m app.scripts.download_models

Models are cached in ~/.cache/huggingface, so later starts work offline.
"""
from app.core.config import settings


def main() -> None:
    from sentence_transformers import CrossEncoder

    from app.services.embeddings import SentenceTransformerEmbedder

    emb = SentenceTransformerEmbedder(settings.EMBEDDING_MODEL)
    v = emb.embed_query("How many days of annual leave do I get?")
    print(f"Embedding model OK: {settings.EMBEDDING_MODEL} (dimension {len(v)})")
    if settings.ENABLE_RERANKER:
        ce = CrossEncoder(settings.RERANKER_MODEL, device="cpu")
        score = ce.predict([("annual leave days", "Employees get 24 days of annual leave.")])
        print(f"Reranker OK: {settings.RERANKER_MODEL} (sample score {float(score[0]):.2f})")


if __name__ == "__main__":
    main()
