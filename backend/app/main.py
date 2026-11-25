"""FastAPI application factory: middleware, error handling, routers.

Run locally:  uvicorn app.main:app --reload
Interactive API docs: http://localhost:8000/docs
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.routes import admin, auth, chat, dashboard, documents, rag, users
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.db.session import SessionLocal, engine
from app.services.document_service import recover_interrupted

setup_logging(settings.LOG_LEVEL)
log = logging.getLogger("corpmind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT != "test":
        with SessionLocal() as db:
            recover_interrupted(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
        title=settings.APP_NAME,
        version="1.0.0",
        description="Enterprise RAG knowledge assistant API",
        docs_url="/docs",
        openapi_url=f"{settings.API_PREFIX}/openapi.json",
    )

    # --- Rate limiting ---
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # --- CORS: only the configured frontend origins ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Adds a request id, security headers, and one access-log line per request (no bodies logged)."""
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path, response.status_code, ms)
        return response

    # --- Error handling: consistent JSON, no stack traces or internals leaked to clients ---
    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please slow down."})

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Validation error", "errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    # --- Routes ---
    for r in (auth.router, users.router, documents.router, rag.router, chat.router, dashboard.router, admin.router):
        app.include_router(r, prefix=settings.API_PREFIX)

    @app.get(f"{settings.API_PREFIX}/health", tags=["health"])
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    return app


app = create_app()
