import logging

from app.core.logging import RedactingFilter
from app.core.rate_limit import limiter


def test_login_rate_limit(client):
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [client.post("/api/v1/auth/login", json={"email": "x@corp.test", "password": "Whatever123"}).status_code
                 for _ in range(12)]
    finally:
        limiter.enabled = False
        limiter.reset()
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


def test_log_redaction():
    f = RedactingFilter()
    rec = logging.LogRecord("t", logging.INFO, "", 0, "key=%s pw password=hunter2 tok eyJa.eyJb.sig", ("sk-abcdefghijklmnop",), None)
    f.filter(rec)
    msg = rec.getMessage()
    assert "sk-abcdefghijklmnop" not in msg and "hunter2" not in msg and "eyJa.eyJb.sig" not in msg
    assert msg.count("[REDACTED]") == 3
