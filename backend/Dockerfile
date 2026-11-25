# CorpMind backend: FastAPI + RAG pipeline.
#   docker build -t corpmind-backend ./backend
# Build arg PRELOAD_MODELS=true (default) downloads the embedding + reranker models into the image,
# so the container starts and answers without internet access to Hugging Face.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# CPU-only PyTorch first (~200 MB instead of ~2 GB with CUDA), then everything else.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 10001 corpmind
COPY --chown=corpmind:corpmind . .
RUN mkdir -p /app/storage /app/.cache/huggingface && chown -R corpmind:corpmind /app/storage /app/.cache \
    && chmod +x /app/scripts/docker-entrypoint.sh
USER corpmind

ARG PRELOAD_MODELS=true
# JWT_SECRET_KEY is only a placeholder so settings load during the build; it is not kept at runtime.
RUN if [ "$PRELOAD_MODELS" = "true" ]; then \
      JWT_SECRET_KEY=build-time-placeholder-not-used-at-runtime-0000 python -m app.scripts.download_models; \
    fi

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
