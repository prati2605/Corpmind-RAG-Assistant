"""Provider-agnostic LLM access via LangChain's `init_chat_model`.

Switch providers by changing two lines in .env:
    LLM_PROVIDER=anthropic          LLM_MODEL=claude-haiku-4-5
    LLM_PROVIDER=openai             LLM_MODEL=gpt-4o-mini
    LLM_PROVIDER=groq               LLM_MODEL=llama-3.3-70b-versatile     (pip install langchain-groq)
    LLM_PROVIDER=google_genai       LLM_MODEL=gemini-2.0-flash             (pip install langchain-google-genai)
    LLM_PROVIDER=ollama             LLM_MODEL=llama3.1                     (pip install langchain-ollama; no key)

The API key comes only from LLM_API_KEY (or the provider's own env var, e.g. OPENAI_API_KEY).
It is passed straight to the client and never logged or returned by any endpoint.
"""
import logging
import threading

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings

log = logging.getLogger("corpmind.llm")


class LLMUnavailable(Exception):
    """The LLM could not be reached or returned an error."""


def build_chat_model(temperature: float | None = None, max_tokens: int | None = None) -> BaseChatModel:
    from langchain.chat_models import init_chat_model

    kwargs: dict = {
        "model": settings.LLM_MODEL,
        "model_provider": settings.LLM_PROVIDER,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        "timeout": 60,
        "max_retries": 2,
    }
    if settings.LLM_PROVIDER == "ollama":
        kwargs["base_url"] = settings.OLLAMA_BASE_URL
        kwargs.pop("timeout")
    elif settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    try:
        return init_chat_model(**kwargs)
    except ImportError as e:
        raise LLMUnavailable(
            f"The integration package for provider '{settings.LLM_PROVIDER}' is not installed "
            f"(e.g. pip install langchain-{settings.LLM_PROVIDER.replace('_', '-')}).") from e
    except Exception as e:
        raise LLMUnavailable(f"Could not configure LLM provider '{settings.LLM_PROVIDER}': {type(e).__name__}") from e


_llm: BaseChatModel | None = None
_lock = threading.Lock()


def get_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        with _lock:
            if _llm is None:
                _llm = build_chat_model()
                log.info("LLM ready: provider=%s model=%s", settings.LLM_PROVIDER, settings.LLM_MODEL)
    return _llm


def set_llm(llm: BaseChatModel | None) -> None:
    """Replace the singleton (used by tests)."""
    global _llm
    _llm = llm


def invoke_text(messages: list) -> str:
    """Call the LLM and return plain text. Provider errors become LLMUnavailable (no internals leaked)."""
    try:
        result = get_llm().invoke(messages)
    except LLMUnavailable:
        raise
    except Exception as e:
        log.error("LLM call failed: %s", type(e).__name__)
        raise LLMUnavailable("The language model is currently unavailable") from e
    content = result.content
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content).strip()
