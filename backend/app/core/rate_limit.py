"""Rate limiting with slowapi.

Keyed by the authenticated user id when a valid bearer token is present (so users
behind one office NAT don't share a bucket), otherwise by client IP.
In-memory storage is fine for a single process; set a Redis storage_uri for multi-worker deployments.
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.security import ACCESS, TokenError, decode_token


def rate_limit_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            return "user:" + decode_token(auth[7:], ACCESS)["sub"]
        except TokenError:
            pass
    return "ip:" + get_remote_address(request)


limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
    headers_enabled=False,
)
