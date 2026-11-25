"""Application settings, loaded from environment variables / .env.

Every secret (JWT key, LLM API key, DB password) comes from the environment.
Nothing secret is hard-coded, and the frontend never sees these values.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from typing import Annotated

from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # .../backend


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    APP_NAME: str = "CorpMind AI"
    ENVIRONMENT: str = "development"  # development | test | production
    API_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg://corpmind:corpmind_dev@localhost:5432/corpmind"

    # --- Auth ---
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALLOW_SELF_REGISTRATION: bool = True  # new users always get the Employee role
    # Only these email domains may self-register (e.g. "northwind.com,northwind.in"). Empty = any domain,
    # which is fine for a demo but means anyone who can reach the site could read Employee documents.
    REGISTRATION_EMAIL_DOMAINS: Annotated[list[str], NoDecode] = []
    # Send the refresh cookie only over HTTPS. Defaults to on in production; set false only for
    # plain-HTTP deployments on a trusted network (browsers treat http://localhost as secure anyway).
    COOKIE_SECURE: bool | None = None

    # --- Rate limiting (slowapi syntax) ---
    RATE_LIMIT_DEFAULT: str = "120/minute"
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_CHAT: str = "20/minute"
    RATE_LIMIT_ENABLED: bool = True

    # --- Uploads ---
    UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
    MAX_UPLOAD_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: Annotated[list[str], NoDecode] = [".pdf", ".docx", ".txt", ".csv"]

    # --- Vector store / embeddings (used from Phase 2) ---
    CHROMA_DIR: Path = BASE_DIR / "storage" / "chroma"
    CHROMA_COLLECTION: str = "corpmind_chunks"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ENABLE_RERANKER: bool = True
    CHUNK_SIZE: int = 900
    CHUNK_OVERLAP: int = 150

    # --- Retrieval (Phase 3) ---
    RETRIEVAL_TOP_K: int = 6
    RETRIEVAL_CANDIDATES: int = 20
    RELEVANCE_THRESHOLD: float = 0.30        # min cosine similarity when the reranker is off
    RERANK_THRESHOLD: float = 0.10           # min cross-encoder relevance (0..1) when the reranker is on
    MAX_CHUNKS_PER_DOCUMENT: int = 4         # diversity: cap chunks from one document in a normal answer
    SUMMARY_MAX_CHARS: int = 14000           # context budget when summarising one document
    COMPARE_MAX_DOCUMENTS: int = 4
    COMPARE_CHUNKS_PER_DOCUMENT: int = 3
    CONFIDENCE_HIGH_RERANK: float = 0.70
    CONFIDENCE_MEDIUM_RERANK: float = 0.35
    CONFIDENCE_HIGH_COSINE: float = 0.55
    CONFIDENCE_MEDIUM_COSINE: float = 0.40
    CHAT_HISTORY_TURNS: int = 6

    # --- LLM (provider-agnostic via LangChain init_chat_model) ---
    LLM_PROVIDER: str = "openai"  # openai | anthropic | groq | google_genai | ollama
    LLM_MODEL: str = "gpt-4o-mini"  # model ids change over time; check your provider's current list
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 1024
    LLM_API_KEY: str | None = None  # read by the provider integration; never logged
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    @field_validator("CORS_ORIGINS", "ALLOWED_EXTENSIONS", "REGISTRATION_EMAIL_DOMAINS", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str) and not v.strip().startswith("["):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def cookie_secure(self) -> bool:
        return self.ENVIRONMENT == "production" if self.COOKIE_SECURE is None else self.COOKIE_SECURE

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
