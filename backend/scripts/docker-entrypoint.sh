#!/bin/sh
# Container start: apply database migrations, then serve the API.
set -e

echo "Applying database migrations..."
alembic upgrade head

# One worker on purpose: document processing runs as in-process background tasks, the embedding
# model is loaded once per process, and rate limits are kept in memory. Scale with more CPU, or
# move ingestion to a queue (Celery/RQ) and rate limits to Redis before adding workers.
# --proxy-headers: trust X-Forwarded-For from nginx so audit logs and rate limits see real client IPs.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
