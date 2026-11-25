"""Logging setup.

Rule for the whole codebase: log identifiers (user id, document id, chunk counts,
latencies), never document text, prompts, answers, passwords or tokens.
The RedactingFilter is a safety net in case a secret-looking value slips into a message.
"""
import logging
import re
import sys

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{10,})"),            # OpenAI-style keys
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]{10,})"),        # Anthropic-style keys
    re.compile(r"(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)"),  # JWTs
    re.compile(r"(?i)(password['\"]?\s*[:=]\s*)(\S+)"),
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = msg
        for p in _SECRET_PATTERNS:
            redacted = p.sub(lambda m: (m.group(1) if m.lastindex and m.lastindex > 1 else "") + "[REDACTED]", redacted)
        if redacted != msg:
            record.msg, record.args = redacted, ()
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Keep noisy libraries quiet
    for noisy in ("httpx", "httpcore", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
